"""
ROV 控制站 —— 应用核心聚合层。

将手柄控制、串口通信、传感器解析、过流检测、摄像头采集
整合为统一的 AppCore 接口，供 GUI 层调用。

═══════════════════════════════════════════════════════
  数据流
═══════════════════════════════════════════════════════

  手柄/键盘 ──→ JoystickController.update()
      │                ↓ ControlState
      │         SerialComm.build_data_frame()
      │                ↓ 下行数据帧
      │          SerialComm.send_frame()
      │                ↓
      │         ═══ 串口 ═══
      │                ↓
      │         CommandBuffer.get_command()
      │                ↓ 上行帧 (15 bytes)
      │         SensorParser.parse()
      │                ↓ SensorData
      │         OvercurrentMonitor.update()
      │
  摄像头 ──→ Camera.get_frame()
"""

import configparser
import os
import threading
import time
from typing import Any, Callable, Optional

from .joystick import JoystickController, ControlState, SpeedMode, MODE_NAMES
from .serial_comm import SerialComm
from .sensor import SensorParser, SensorData, OvercurrentMonitor
from .camera import Camera
from .utils import FrameRateLimiter, Stopwatch

# ───────── 路径 ─────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG = os.path.join(_BASE_DIR, "config", "config.ini")


# ════════════════════════════════════════════════════════
#  回调类型
# ════════════════════════════════════════════════════════

class AppCallbacks:
    """GUI 可注册的回调集合"""
    on_sensor_data: Optional[Callable[[SensorData], None]] = None       # 收到传感器数据
    on_overcurrent_enter: Optional[Callable[[float], None]] = None      # 进入过流(电流值)
    on_overcurrent_exit: Optional[Callable[[float, float], None]] = None  # 退出过流(电流值, 持续秒)
    on_connection_changed: Optional[Callable[[bool], None]] = None      # 串口连接状态变化
    on_joystick_changed: Optional[Callable[[bool], None]] = None        # 手柄连接状态变化


# ════════════════════════════════════════════════════════
#  应用核心
# ════════════════════════════════════════════════════════

class AppCore:
    """
    ROV 控制站应用核心。

    使用方法:
        app = AppCore()
        app.set_callbacks(...)
        app.start(port='COM8', baudrate=115200)
        ...
        cs = app.update()          # 每帧调用（~125 Hz）
        frame = app.get_frame()    # 获取摄像头帧
        app.stop()
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = config_path or _DEFAULT_CONFIG

        # ── 加载配置 ──
        self._cfg = self._load_config()

        # ── 子系统 ──
        self._joystick: Optional[JoystickController] = None
        self._serial: Optional[SerialComm] = None
        self._overcurrent: Optional[OvercurrentMonitor] = None
        self._camera: Optional[Camera] = None

        # ── 回调 ──
        self._callbacks = AppCallbacks()

        # ── 状态 ──
        self._latest_control: Optional[ControlState] = None
        self._latest_sensor: Optional[SensorData] = None

        # ── 频率控制 ──
        self._limiter: Optional[FrameRateLimiter] = None

        # ── 秒表（用于任务计时等） ──
        self._stopwatch = Stopwatch()

        # ── 请求帧定时发送 ──
        self._request_interval = 0.2  # 200ms 发送一次请求帧
        self._request_timer_thread: Optional[threading.Thread] = None

    # ── 配置加载 ──
    def _load_config(self) -> configparser.ConfigParser:
        cfg = configparser.ConfigParser()
        if os.path.exists(self._config_path):
            cfg.read(self._config_path, encoding="utf-8")
        return cfg

    def _get_cfg(self, section: str, key: str, fallback: Any = None, conv: type = str) -> Any:
        """安全读取配置项"""
        try:
            val = self._cfg.get(section, key)
            return conv(val)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback

    # ── 回调注册 ──
    def set_callbacks(self, callbacks: AppCallbacks) -> None:
        """注册 GUI 回调"""
        self._callbacks = callbacks
        if self._overcurrent:
            self._overcurrent.set_callbacks(
                on_enter=callbacks.on_overcurrent_enter,
                on_exit=callbacks.on_overcurrent_exit,
            )

    # ── 启动 / 停止 ──
    def start(
        self,
        port: str,
        baudrate: int = 115200,
        camera_id: int = 0,
        camera_width: int = 640,
        camera_height: int = 480,
        control_freq: float = 125.0,
    ) -> bool:
        """
        启动所有子系统。
        :param port:          串口号（如 'COM8'）
        :param baudrate:      波特率
        :param camera_id:     摄像头 ID
        :param camera_width:  摄像头宽
        :param camera_height: 摄像头高
        :param control_freq:  控制循环频率（Hz）
        :return:              串口是否连接成功
        """
        # ── 频率控制 ──
        self._limiter = FrameRateLimiter(control_freq)

        # ── 手柄 ──
        self._joystick = JoystickController(self._config_path)
        if self._callbacks.on_joystick_changed:
            self._callbacks.on_joystick_changed(self._joystick.has_joystick)

        # ── 过流监控 ──
        threshold = self._get_cfg("overcurrent", "threshold", 10.0, float)
        self._overcurrent = OvercurrentMonitor(threshold=threshold)
        self._overcurrent.set_callbacks(
            on_enter=self._callbacks.on_overcurrent_enter,
            on_exit=self._callbacks.on_overcurrent_exit,
        )

        # ── 串口 ──
        timeout = 0.05
        poll_interval = 0.001
        self._serial = SerialComm(port, baudrate, timeout, poll_interval)
        self._serial.set_callback(self._on_serial_frame)
        connected = self._serial.connect()

        if self._callbacks.on_connection_changed:
            self._callbacks.on_connection_changed(connected)

        if connected:
            # 启动请求帧定时发送线程
            self._start_request_timer()

        # ── 摄像头 ──
        self._camera = Camera(camera_id, camera_width, camera_height)
        self._camera.start()

        return connected

    def stop(self) -> None:
        """停止所有子系统并释放资源"""
        # 停止请求帧定时器
        self._stop_request_timer()

        if self._camera:
            self._camera.stop()
            self._camera = None

        if self._serial:
            self._serial.disconnect()
            self._serial = None

        if self._joystick:
            self._joystick.close()
            self._joystick = None

    # ── 每帧更新 ──
    def update(self) -> ControlState:
        """
        每帧调用一次（推荐 125 Hz）。
        读取手柄 → 发送下行数据帧 → 返回 ControlState。
        """
        if self._joystick is None:
            return ControlState()

        cs = self._joystick.update()
        self._latest_control = cs

        # 发送下行数据帧
        if self._serial and self._serial.is_connected():
            frame = SerialComm.build_data_frame(
                thrust_y=cs.thrust_y,
                thrust_x=cs.thrust_x,
                thrust_z=cs.thrust_z,
                yaw_torque=cs.yaw_torque,
                arm_angle=cs.arm_angle,
            )
            self._serial.send_frame(frame)

        return cs

    # ── 摄像头 ──
    def get_frame(self):
        """获取最新摄像头帧（BGR numpy 数组）"""
        if self._camera:
            return self._camera.get_frame()
        return None

    def get_frame_rgb(self):
        """获取最新摄像头帧（RGB 格式，适用于 Qt）"""
        if self._camera:
            return self._camera.get_frame_rgb()
        return None

    def snapshot(self, filepath: str) -> bool:
        """保存当前帧截图"""
        if self._camera:
            return self._camera.snapshot(filepath)
        return False

    # ── 录像（进阶挑战） ──
    @property
    def is_recording(self) -> bool:
        return self._camera is not None and self._camera.is_recording

    @property
    def record_duration(self) -> float:
        return self._camera.record_duration if self._camera else 0.0

    def start_recording(self, filepath: str) -> bool:
        """开始录像"""
        if self._camera:
            return self._camera.start_recording(filepath)
        return False

    def stop_recording(self) -> str:
        """停止录像，返回文件路径"""
        if self._camera:
            return self._camera.stop_recording()
        return ""

    # ── 秒表（进阶挑战） ──
    @property
    def stopwatch(self) -> Stopwatch:
        """获取秒表实例（用于任务计时等）"""
        return self._stopwatch

    # ── 频率控制 ──
    def wait_frame(self) -> float:
        """阻塞至下一帧（配合 FrameRateLimiter），返回实际间隔（秒）"""
        if self._limiter:
            return self._limiter.wait()
        time.sleep(0.008)  # 默认 ~125Hz
        return 0.008

    @property
    def actual_control_fps(self) -> float:
        """实际控制循环帧率"""
        return self._limiter.actual_fps if self._limiter else 0.0

    # ── 请求帧定时器 ──
    def _start_request_timer(self) -> None:
        """启动后台线程，定时发送下行请求帧"""
        self._stop_request_timer()
        self._request_timer_thread = threading.Thread(
            target=self._request_timer_loop, daemon=True
        )
        self._request_timer_thread.start()

    def _stop_request_timer(self) -> None:
        if self._request_timer_thread is not None:
            # daemon 线程会自动退出
            self._request_timer_thread = None

    def _request_timer_loop(self) -> None:
        """后台线程：定时发送请求帧以获取传感器数据"""
        while self._serial and self._serial.is_connected():
            try:
                frame = SerialComm.build_request_frame()
                self._serial.send_frame(frame)
            except Exception:
                pass
            time.sleep(self._request_interval)

    # ── 串口回调 ──
    def _on_serial_frame(self, raw_frame: bytes) -> None:
        """
        SerialComm 收到完整上行帧时的回调。
        解析传感器数据 → 更新过流监控 → 通知 GUI。
        """
        sensor = SensorParser.parse(raw_frame)
        self._latest_sensor = sensor

        # 更新过流监控
        if self._overcurrent:
            self._overcurrent.update(sensor.current, sensor.timestamp)

        # 通知 GUI
        if self._callbacks.on_sensor_data:
            self._callbacks.on_sensor_data(sensor)

    # ── 状态查询 ──
    @property
    def latest_control(self) -> Optional[ControlState]:
        """最近一次控制状态"""
        return self._latest_control

    @property
    def latest_sensor(self) -> Optional[SensorData]:
        """最近一次传感器数据"""
        return self._latest_sensor

    @property
    def is_serial_connected(self) -> bool:
        return self._serial is not None and self._serial.is_connected()

    @property
    def has_joystick(self) -> bool:
        return self._joystick is not None and self._joystick.has_joystick

    @property
    def is_camera_connected(self) -> bool:
        return self._camera is not None and self._camera.is_connected

    @property
    def overcurrent_status(self) -> dict:
        if self._overcurrent:
            return self._overcurrent.get_status_dict()
        return {"is_overcurrent": False, "threshold": 0.0, "total_overcurrent_time": 0.0}

    @property
    def camera_actual_fps(self) -> float:
        return self._camera.actual_fps if self._camera else 0.0

    def get_joystick_controller(self) -> Optional[JoystickController]:
        """获取手柄控制器引用（供 GUI 直接查询模式等）"""
        return self._joystick

    def reset_overcurrent_statistics(self) -> None:
        """重置过流累计时间统计"""
        if self._overcurrent:
            self._overcurrent.reset_statistics()
