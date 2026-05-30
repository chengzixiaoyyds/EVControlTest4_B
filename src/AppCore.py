"""
应用核心 —— 子系统聚合层，唯一有权读取 config.ini 的模块。

职责:
  - 加载配置 → 分发给各子系统
  - 编排数据流: 手柄 → 串口下发, 串口上行 → 传感器解析 → 过流监控 → GUI
  - 暴露统一接口给 main.py

不负责: UI 渲染、协议解析、硬件驱动。
"""

import configparser
import os
import threading
import time
from typing import Any, Callable, Optional

from .joystick import JoystickController, ControlState
from .serial_comm import SerialComm
from .sensor import SensorParser, SensorData, OvercurrentMonitor
from .camera import Camera
from .utils import Stopwatch

# ───────── 路径 ─────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG = os.path.join(_BASE_DIR, "config", "config.ini")


# ════════════════════════════════════════════════════════
#  回调类型
# ════════════════════════════════════════════════════════

class AppCallbacks:
    """GUI 回调集合 —— AppCore 通过它们把数据推送给 MainWindow，避免反向依赖。"""
    on_sensor_data: Optional[Callable[[SensorData], None]] = None       # 收到传感器数据
    on_overcurrent_enter: Optional[Callable[[float], None]] = None      # 进入过流(电流值)
    on_overcurrent_exit: Optional[Callable[[float, float], None]] = None  # 退出过流(电流值, 持续秒)
    on_overcurrent_threshold: Optional[Callable[[float], None]] = None  # 过流阈值同步
    on_connection_changed: Optional[Callable[[bool], None]] = None      # 串口连接状态变化
    on_joystick_changed: Optional[Callable[[bool], None]] = None        # 手柄连接状态变化
    on_mode_names: Optional[Callable[[dict], None]] = None              # 速度档位名称同步


# ════════════════════════════════════════════════════════
#  应用核心
# ════════════════════════════════════════════════════════

class AppCore:
    """
    系统组装器 —— 创建并连接所有子系统，暴露统一控制接口。

    只做编排，不做具体工作：
      手柄 → JoystickController
      通信 → SerialComm
      解析 → SensorParser
      监控 → OvercurrentMonitor
      视频 → Camera
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

        # ── 线程安全 ──
        self._state_lock = threading.Lock()   # 保护 _latest_control / _latest_sensor
        self._serial_lock = threading.Lock()  # 保护 _serial 引用（独立于数据锁，避免语义混淆）

        # ── 状态 ──
        self._latest_control: Optional[ControlState] = None
        self._latest_sensor: Optional[SensorData] = None

        # ── 秒表（用于任务计时等） ──
        self._stopwatch = Stopwatch()

        # ── 媒体输出 ──
        self._screenshot_counter = 0
        self._screenshot_dir = ""
        self._record_dir = ""

        # ── 请求帧定时发送（间隔由 config.ini [serial] request_interval 控制）──
        self._request_interval = 0.2  # 默认值，start() 中从 config 覆盖
        self._request_timer_thread: Optional[threading.Thread] = None
        self._request_timer_stop = threading.Event()
        self._shutting_down = threading.Event()  # 关闭标志（跨线程可见），阻止 stop() 后重启定时器

        # ── 手柄热插拔检测（在主线程 update() 中按时间间隔执行，避免 pygame 多线程问题）──
        self._joystick_poll_interval = 1.0  # 默认值，start() 中从 config 覆盖
        self._last_joystick_poll: float = 0.0

    # === 配置 ===
    def _load_config(self) -> configparser.ConfigParser:
        cfg = configparser.ConfigParser()
        if os.path.exists(self._config_path):
            cfg.read(self._config_path, encoding="utf-8")
        return cfg

    def _get_cfg(self, section: str, key: str, fallback: Any = None, conv: type = str) -> Any:
        """
        安全读取单个配置项。
        :param section:  配置节名，如 "serial"
        :param key:      配置键名，如 "port"
        :param fallback: 默认值（节或键不存在时返回）
        :param conv:     类型转换函数，如 int / float
        """
        try:
            val = self._cfg.get(section, key)
            return conv(val)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback

    # === 回调注册 ===
    def set_callbacks(self, callbacks: AppCallbacks) -> None:
        """注册 GUI 回调"""
        self._callbacks = callbacks
        if self._overcurrent:
            self._overcurrent.set_callbacks(
                on_enter=callbacks.on_overcurrent_enter,
                on_exit=callbacks.on_overcurrent_exit,
            )

    # === 启动 / 停止 ===
    def start(self) -> bool:
        """
        启动所有子系统，所有参数从 config.ini 读取。
        :return: 串口是否连接成功
        """
        # ── 手柄 ──
        jc_kb  = self._section_dict("keyboard")
        jc_joy = self._section_dict("joystick")
        jc_axes = {n: self._section_dict(n) for n in ("x", "y", "z", "yaw") if self._cfg.has_section(n)}
        jc_spd  = self._section_dict("speed_modes")
        self._joystick = JoystickController(jc_kb, jc_joy, jc_axes, jc_spd)
        if self._callbacks.on_joystick_changed:
            self._callbacks.on_joystick_changed(self._joystick.has_joystick)
        if self._callbacks.on_mode_names:
            self._callbacks.on_mode_names(self._joystick.mode_names)

        # ── 手柄热插拔检测间隔 ──
        self._joystick_poll_interval = self._get_cfg("joystick", "poll_interval", 1.0, float)

        # ── 过流监控 ──
        threshold = self._get_cfg("overcurrent", "threshold", 10.0, float)
        self._overcurrent = OvercurrentMonitor(threshold=threshold)
        self._overcurrent.set_callbacks(
            on_enter=self._callbacks.on_overcurrent_enter,
            on_exit=self._callbacks.on_overcurrent_exit,
        )
        # 同步阈值到 UI
        if self._callbacks.on_overcurrent_threshold:
            self._callbacks.on_overcurrent_threshold(threshold)

        # ── 串口 ──
        port = self._get_cfg("serial", "port", "COM8")
        baudrate = self._get_cfg("serial", "baudrate", 115200, int)
        timeout = self._get_cfg("serial", "timeout", 0.05, float)
        poll_interval = self._get_cfg("serial", "poll_interval", 0.001, float)
        reconnect_interval = self._get_cfg("serial", "reconnect_interval", 2.0, float)
        request_interval = self._get_cfg("serial", "request_interval", 0.2, float)
        self._request_interval = request_interval
        with self._serial_lock:
            self._serial = SerialComm(port, baudrate, timeout, poll_interval, reconnect_interval)
        self._serial.set_callback(self._on_serial_frame)
        self._serial.set_status_callback(self._on_serial_status)
        connected = self._serial.connect()
        # 注意: connect() 内部已通过 _set_connected → _on_serial_status
        # 自动触发 on_connection_changed 和 _start_request_timer()，无需重复调用

        # ── 手柄热插拔检测（内联到 update() 中，避免 pygame 多线程问题）──
        self._last_joystick_poll = time.time()

        # ── 摄像头 ──
        camera_id = self._get_cfg("camera", "id", 0, int)
        camera_width = self._get_cfg("camera", "width", 640, int)
        camera_height = self._get_cfg("camera", "height", 480, int)
        self._camera = Camera(camera_id, camera_width, camera_height)
        if not self._camera.start():
            print("[AppCore] 警告: 摄像头启动失败")
            self._camera = None

        # ── 媒体输出路径 ──
        media = self._section_dict("media")
        self._screenshot_dir = os.path.join(_BASE_DIR, media.get("screenshot_dir", "screenshots"))
        self._record_dir = os.path.join(_BASE_DIR, media.get("record_dir", "recordings"))
        os.makedirs(self._screenshot_dir, exist_ok=True)
        os.makedirs(self._record_dir, exist_ok=True)

        # ── 快捷键绑定（内部完成，不暴露给 main.py）──
        if self._joystick:
            self._joystick.set_action_callback("snapshot", self.snapshot)
            self._joystick.set_action_callback("record", self.toggle_recording)

        return connected

    def stop(self) -> None:
        """停止所有子系统并释放资源"""
        # 先置关闭标志（Event.set() 保证跨线程内存可见性），阻止串口重连回调重启请求帧定时器
        self._shutting_down.set()
        self._stop_request_timer()

        # 先断开串口（切断数据源），再停止消费者（摄像头），避免回调在事件循环停止后触发
        with self._serial_lock:
            if self._serial:
                self._serial.disconnect()
                self._serial = None

        if self._camera:
            self._camera.stop()
            self._camera = None

        if self._joystick:
            self._joystick.close()
            self._joystick = None

    # === 每帧更新（125Hz，主循环调用）===
    def update(self) -> Optional[ControlState]:
        """
        每帧调用一次（推荐 125 Hz）。
        读取手柄 → 发送下行数据帧 → 返回 ControlState。
        手柄热插拔检测也在此处（按时间间隔触发），避免 pygame 多线程访问。
        当 _joystick 未初始化时返回 None，调用方应跳过后续处理。
        """
        if self._joystick is None:
            return None

        # ── 手柄热插拔检测（主线程中执行，线程安全）──
        now = time.time()
        if now - self._last_joystick_poll >= self._joystick_poll_interval:
            self._last_joystick_poll = now
            prev = self._joystick.has_joystick
            cur = self._joystick.refresh_joystick()
            if cur != prev and self._callbacks.on_joystick_changed:
                self._callbacks.on_joystick_changed(cur)

        cs = self._joystick.update()

        # 发送下行数据帧
        with self._serial_lock:
            serial = self._serial
        if serial is not None and serial.is_connected():
            frame = SerialComm.build_data_frame(
                thrust_y=cs.thrust_y,
                thrust_x=cs.thrust_x,
                thrust_z=cs.thrust_z,
                yaw_torque=cs.yaw_torque,
                arm_angle=cs.arm_angle,
            )
            serial.send_frame(frame)

        with self._state_lock:
            self._latest_control = cs

        return cs

    # === 摄像头 ===
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

    def snapshot(self) -> str:
        """截图（自动生成路径），返回文件路径，失败返回空字符串"""
        if not self._camera:
            return ""
        self._screenshot_counter += 1
        path = os.path.join(self._screenshot_dir, f"screenshot_{self._screenshot_counter:04d}.png")
        ok = self._camera.snapshot(path)
        if ok:
            print(f"[AppCore] 截图 → {path}")
        return path if ok else ""

    # --- 录像 ---
    @property
    def is_recording(self) -> bool:
        return self._camera is not None and self._camera.is_recording

    @property
    def record_duration(self) -> float:
        return self._camera.record_duration if self._camera else 0.0

    def start_recording(self) -> str:
        """开始录像（自动生成路径），返回文件路径，失败返回空字符串"""
        if not self._camera:
            return ""
        path = os.path.join(self._record_dir, f"record_{time.strftime('%Y%m%d_%H%M%S')}.avi")
        ok = self._camera.start_recording(path)
        return path if ok else ""

    def stop_recording(self) -> str:
        """停止录像，返回文件路径"""
        if self._camera:
            return self._camera.stop_recording()
        return ""

    def toggle_recording(self) -> bool:
        """切换录像状态，返回当前是否录像中"""
        if self.is_recording:
            self.stop_recording()
            return False
        else:
            return bool(self.start_recording())

    # === 秒表 ===
    @property
    def stopwatch(self) -> Stopwatch:
        """获取秒表实例（供主循环读取 elapsed 等属性）"""
        return self._stopwatch

    def toggle_stopwatch(self) -> None:
        """切换秒表：运行→暂停，暂停→恢复，停止→开始"""
        sw = self._stopwatch
        if sw.is_running:
            sw.pause()
        else:
            sw.resume() if sw.elapsed > 0 else sw.start()

    def reset_stopwatch(self) -> None:
        """重置秒表"""
        self._stopwatch.reset()

    @property
    def stopwatch_elapsed(self) -> float:
        """秒表已用时间（秒），供主循环读取，避免穿透 AppCore 直接访问子对象"""
        return self._stopwatch.elapsed

    @property
    def stopwatch_is_running(self) -> bool:
        """秒表是否正在运行"""
        return self._stopwatch.is_running

    # === 请求帧定时器 ===
    def _start_request_timer(self) -> None:
        """启动后台线程，每 200ms 发送下行请求帧(0x52 'R')，触发下位机回传传感器数据"""
        if self._shutting_down.is_set():
            return  # 正在关闭，拒绝启动新定时器
        self._stop_request_timer()
        self._request_timer_stop.clear()
        self._request_timer_thread = threading.Thread(
            target=self._request_timer_loop, daemon=True
        )
        self._request_timer_thread.start()

    def _stop_request_timer(self) -> None:
        """停止请求帧后台线程"""
        self._request_timer_stop.set()
        if self._request_timer_thread is not None:
            self._request_timer_thread.join(timeout=1.0)
            self._request_timer_thread = None

    def _request_timer_loop(self) -> None:
        """后台线程：定时发送下行请求帧(0x52 'R')，下位机收到后才回传上行数据帧(0x53 'S')"""
        while not self._request_timer_stop.is_set():
            # 使用独立 _serial_lock 读取设备引用，避免与数据锁竞争
            with self._serial_lock:
                serial = self._serial
            if serial is not None and serial.is_connected():
                try:
                    frame = SerialComm.build_request_frame()
                    serial.send_frame(frame)
                except Exception as e:
                    print(f"[AppCore] 请求帧发送异常: {e}")
            self._request_timer_stop.wait(self._request_interval)

    # === 串口状态回调 ===
    def _on_serial_status(self, connected: bool) -> None:
        """
        SerialComm 连接状态变化时的回调。
        连接恢复时重启请求帧定时器，断开时停止。
        """
        if connected:
            self._start_request_timer()
        else:
            self._stop_request_timer()

        # 通知 GUI
        if self._callbacks.on_connection_changed:
            self._callbacks.on_connection_changed(connected)

    # === 串口回调 ===
    def _on_serial_frame(self, raw_frame: bytes) -> None:
        """
        SerialComm 收到完整上行帧时的回调。
        解析传感器数据 → 更新过流监控 → 通知 GUI。
        """
        sensor = SensorParser.parse(raw_frame)

        # 更新过流监控
        if self._overcurrent:
            self._overcurrent.update(sensor.current, sensor.timestamp)

        with self._state_lock:
            self._latest_sensor = sensor

        # 通知 GUI
        if self._callbacks.on_sensor_data:
            self._callbacks.on_sensor_data(sensor)

    # === 状态查询 ===
    @property
    def latest_control(self) -> Optional[ControlState]:
        """最近一次控制状态"""
        with self._state_lock:
            return self._latest_control

    @property
    def latest_sensor(self) -> Optional[SensorData]:
        """最近一次传感器数据"""
        with self._state_lock:
            return self._latest_sensor

    @property
    def is_serial_connected(self) -> bool:
        """串口是否已连接"""
        with self._serial_lock:
            serial = self._serial
        return serial is not None and serial.is_connected()

    @property
    def has_joystick(self) -> bool:
        """是否检测到物理手柄"""
        return self._joystick is not None and self._joystick.has_joystick

    @property
    def is_camera_connected(self) -> bool:
        """摄像头是否正常采集"""
        return self._camera is not None and self._camera.is_connected

    @property
    def overcurrent_status(self) -> dict:
        """过流状态摘要 {is_overcurrent, threshold, total_overcurrent_time}"""
        if self._overcurrent:
            return self._overcurrent.get_status_dict()
        return {"is_overcurrent": False, "threshold": 0.0, "total_overcurrent_time": 0.0}

    @property
    def overcurrent_time(self) -> float:
        """过流累计总时间（秒），供主循环直接读取，避免硬编码字典键"""
        if self._overcurrent:
            return self._overcurrent.total_overcurrent_time
        return 0.0

    @property
    def camera_actual_fps(self) -> float:
        """摄像头实际采集帧率"""
        return self._camera.actual_fps if self._camera else 0.0

    # === 配置暴露 ===
    @property
    def keyboard_config(self) -> dict:
        """键盘映射配置 dict → MainWindow → KeyBridge"""
        return self._section_dict("keyboard")

    @property
    def media_config(self) -> dict:
        """媒体输出路径 {screenshot_dir, record_dir} → main.py"""
        return self._section_dict("media")

    @property
    def control_frequency(self) -> float:
        """控制循环频率 (Hz) → main.py 主循环"""
        return self._get_cfg("control", "frequency", 125.0, float)

    def _section_dict(self, section: str) -> dict:
        """将配置段转为普通 dict，供子系统使用（避免传递 ConfigParser 对象）"""
        if self._cfg.has_section(section):
            return dict(self._cfg.items(section))
        return {}

    def reset_overcurrent_statistics(self) -> None:
        """重置过流累计时间统计"""
        if self._overcurrent:
            self._overcurrent.reset_statistics()
        print("[AppCore] 过流统计已重置")
