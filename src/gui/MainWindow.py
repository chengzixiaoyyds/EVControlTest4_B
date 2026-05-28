"""
ROV 控制站 —— 主界面 (PySide6)

界面由 ui/main_window.ui 通过 pyside6-uic 编译生成 Ui_MainWindow。
修改布局请编辑 .ui 文件后重新运行:
    pyside6-uic ui/main_window.ui -o src/gui/Ui_MainWindow.py

布局结构：
┌──────────────┬────────────────────────┐
│              │  串口/手柄 连接状态      │
│   视频画面    │  运动模式 SLOW/MED/FAST │
│   640×480    │  夹爪状态               │
│              │  控制量 (thrust/yaw)     │
│              │  传感器 (温度/电流/进水)  │
│              │  过流保护 (状态/累计)     │
├──────────────┴────────────────────────┤
│  状态栏: 串口 | 手柄 | 帧率 | 录像     │
└───────────────────────────────────────┘
"""

from typing import Optional
import configparser
import os

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QPixmap, QKeyEvent
from PySide6.QtWidgets import QMainWindow, QLabel

import numpy as np
import pygame

from .Ui_MainWindow import Ui_MainWindow
from ..sensor import SensorData
from ..joystick import ControlState, SpeedMode, MODE_NAMES


# ── 路径 ──
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_CONFIG = os.path.join(_BASE_DIR, "config", "config.ini")

# ── 键名覆盖表 ──
# 格式: {config.ini 键名: (Qt.Key 属性名, pygame 属性名)}
# 仅收录 Qt 或 pygame 命名不遵循 Key_<name> / K_<name> 规则的按键。
# 未列出的按键通过动态反射自动解析（覆盖 ~95% 的场景）。
_KEY_OVERRIDE: dict[str, tuple[str, str]] = {
    # config 键名     → (Qt.Key 属性,        pygame 属性)
    "Shift":           ("Key_Shift",        "K_LSHIFT"),         # pygame 无 K_SHIFT
    "Control":         ("Key_Control",      "K_LCTRL"),          # pygame 无 K_CONTROL
    "Alt":             ("Key_Alt",          "K_LALT"),           # pygame 无 K_ALT
    "Meta":            ("Key_Meta",         "K_LMETA"),          # pygame 无 K_META
    "Enter":           ("Key_Enter",        "K_RETURN"),         # pygame 用 K_RETURN
    "Equal":           ("Key_Equal",        "K_EQUALS"),         # pygame 用 K_EQUALS
    "BracketLeft":     ("Key_BracketLeft",  "K_LEFTBRACKET"),    # pygame 命名不同
    "BracketRight":    ("Key_BracketRight", "K_RIGHTBRACKET"),   # pygame 命名不同
    "Backquote":       ("Key_QuoteLeft",    "K_BACKQUOTE"),      # Qt 用 Key_QuoteLeft
    "QuoteDbl":        ("Key_QuoteDbl",     "K_QUOTEDBL"),       # Qt/pygame 均非标准名
}


# ── 样式常量 ──
S_NORMAL = "color: #0f0; font-weight: bold;"
S_WARN   = "color: #f00; font-weight: bold;"
S_DIM    = "color: #888;"
S_YELLOW = "color: #ff0; font-weight: bold;"


# ════════════════════════════════════════════════════
#  MainWindow
# ════════════════════════════════════════════════════

class MainWindow(QMainWindow, Ui_MainWindow):
    """ROV 控制站主窗口"""

    # ── 信号（跨线程安全） ──
    sig_sensor_update      = Signal(object)   # SensorData
    sig_control_update     = Signal(object)   # ControlState
    sig_connection_update  = Signal(bool)
    sig_joystick_update    = Signal(bool)
    sig_overcurrent_update = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setupUi(self)        # Ui_MainWindow 生成所有控件
        self._fix_statusbar()     # 修复状态栏控件布局
        self._load_key_mapping()  # 从 config.ini 加载按键映射
        self._init_state()
        self._apply_styles()
        self._connect_signals()

    # ── 修复状态栏 ──
    def _fix_statusbar(self) -> None:
        """创建状态栏标签并通过 addPermanentWidget 正确布局"""
        sb = QMainWindow.statusBar(self)  # 始终返回正确的 QStatusBar
        self.statusSerial = QLabel("串口: --")
        self.statusJoystick = QLabel("手柄: --")
        self.statusFps = QLabel("FPS: --")
        self.statusRecord = QLabel("")
        for lbl in (self.statusSerial, self.statusJoystick, self.statusFps, self.statusRecord):
            sb.addPermanentWidget(lbl)

    # ── 初始化 ──
    def _init_state(self) -> None:
        self._sensor: Optional[SensorData] = None
        self._control: Optional[ControlState] = None
        self._serial_connected = False
        self._joystick_connected = False
        self._overcurrent_status: dict = {}
        self._fps = 0.0

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(50)
        self._ui_timer.timeout.connect(self._on_tick)

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; }
            QLabel { color: #ccc; }
            QGroupBox {
                font-weight: bold; color: #aaa;
                border: 1px solid #555; border-radius: 4px;
                margin-top: 10px; padding-top: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 4px;
            }
            QPushButton { padding: 6px 16px; color: #ccc; background: #444;
                          border: 1px solid #666; border-radius: 3px; }
            QPushButton:hover { background: #555; }
            QPushButton:checked { background: #600; color: #f66; }
        """)
        self.lblSerial.setStyleSheet(S_DIM)
        self.lblJoystick.setStyleSheet(S_DIM)

        # 禁用按钮焦点，防止方向键切换按钮选中
        for btn in (self.btnSnapshot, self.btnRecord, self.btnResetOc, self.btnStopwatch, self.btnStopwatchReset):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _connect_signals(self) -> None:
        t = Qt.ConnectionType.QueuedConnection
        self.sig_sensor_update.connect(self._slot_sensor, t)
        self.sig_control_update.connect(self._slot_control, t)
        self.sig_connection_update.connect(self._slot_serial, t)
        self.sig_joystick_update.connect(self._slot_joystick, t)
        self.sig_overcurrent_update.connect(self._slot_overcurrent, t)

    # ════════════════════════════════════════════════
    #  公共接口（main.py 调用）
    # ════════════════════════════════════════════════

    def set_callbacks_ref(self, callbacks) -> None:
        callbacks.on_sensor_data        = self._cb_sensor
        callbacks.on_overcurrent_enter  = self._cb_oc_enter
        callbacks.on_overcurrent_exit   = self._cb_oc_exit
        callbacks.on_connection_changed = self._cb_serial
        callbacks.on_joystick_changed   = self._cb_joystick

    def start_ui_timer(self) -> None:
        self._ui_timer.start()

    def stop_ui_timer(self) -> None:
        self._ui_timer.stop()

    def bind_snapshot(self, callback) -> None:
        self.btnSnapshot.clicked.connect(callback)

    def bind_record_toggle(self, callback) -> None:
        self.btnRecord.toggled.connect(callback)

    def bind_reset_overcurrent(self, callback) -> None:
        self.btnResetOc.clicked.connect(callback)

    def bind_stopwatch_toggle(self, callback) -> None:
        self.btnStopwatch.clicked.connect(callback)

    def bind_stopwatch_reset(self, callback) -> None:
        self.btnStopwatchReset.clicked.connect(callback)

    # ── 视频 ──
    def update_video_frame(self, frame_rgb: Optional[np.ndarray]) -> None:
        if frame_rgb is None:
            return
        h, w_img, ch = frame_rgb.shape
        qimg = QImage(frame_rgb.data, w_img, h, ch * w_img, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg).scaled(
            self.videoLabel.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.videoLabel.setPixmap(pix)

    # ── 过流时间 ──
    def update_overcurrent_time(self, seconds: float) -> None:
        h = int(seconds) // 3600
        m = (int(seconds) % 3600) // 60
        s = int(seconds) % 60
        self.lblOcTime.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def update_fps(self, fps: float) -> None:
        self._fps = fps

    def update_record_status(self, recording: bool, duration: float = 0.0) -> None:
        if recording:
            m, s = int(duration) // 60, int(duration) % 60
            self.btnRecord.setText("■ 停止录像")
            self.statusRecord.setText(f"● 录像中 {m:02d}:{s:02d}")
        else:
            self.btnRecord.setText("● 录像")
            self.statusRecord.setText("")

    def update_stopwatch_display(self, elapsed: float, running: bool) -> None:
        """更新秒表显示"""
        h = int(elapsed) // 3600
        m = (int(elapsed) % 3600) // 60
        s = int(elapsed) % 60
        self.lblStopwatch.setText(f"{h:02d}:{m:02d}:{s:02d}")
        if running:
            self.btnStopwatch.setText("⏸ 暂停")
        else:
            self.btnStopwatch.setText("▶ 开始")

    # ════════════════════════════════════════════════
    #  回调 → 信号（后台线程 → UI 线程）
    # ════════════════════════════════════════════════

    def _cb_sensor(self, data: SensorData) -> None:
        self.sig_sensor_update.emit(data)

    def _cb_oc_enter(self, current: float) -> None:
        self.sig_overcurrent_update.emit({"event": "enter", "current": current})

    def _cb_oc_exit(self, current: float, duration: float) -> None:
        self.sig_overcurrent_update.emit({"event": "exit", "current": current})

    def _cb_serial(self, connected: bool) -> None:
        self.sig_connection_update.emit(connected)

    def _cb_joystick(self, connected: bool) -> None:
        self.sig_joystick_update.emit(connected)

    # ════════════════════════════════════════════════
    #  定时刷新 (50 Hz)
    # ════════════════════════════════════════════════

    def _on_tick(self) -> None:
        if self._sensor:
            self._refresh_sensor(self._sensor)
        if self._control:
            self._refresh_control(self._control)
        self.statusFps.setText(f"FPS: {self._fps:.0f}")

    # ════════════════════════════════════════════════
    #  Slot（UI 线程安全）
    # ════════════════════════════════════════════════

    @Slot(object)
    def _slot_sensor(self, data: SensorData) -> None:
        self._sensor = data
        self._refresh_sensor(data)

    @Slot(object)
    def _slot_control(self, cs: ControlState) -> None:
        self._control = cs
        self._refresh_control(cs)

    @Slot(bool)
    def _slot_serial(self, ok: bool) -> None:
        self._serial_connected = ok
        if ok:
            self.lblSerial.setText("串口: ● 已连接")
            self.lblSerial.setStyleSheet(S_NORMAL)
            self.statusSerial.setText("串口: ● 已连接")
        else:
            self.lblSerial.setText("串口: ○ 未连接")
            self.lblSerial.setStyleSheet(S_DIM)
            self.statusSerial.setText("串口: ○ 未连接")

    @Slot(bool)
    def _slot_joystick(self, ok: bool) -> None:
        self._joystick_connected = ok
        if ok:
            self.lblJoystick.setText("手柄: ● 已连接")
            self.lblJoystick.setStyleSheet(S_NORMAL)
            self.statusJoystick.setText("手柄: ● 已连接")
        else:
            self.lblJoystick.setText("手柄: ○ 键盘模式")
            self.lblJoystick.setStyleSheet("color: #f80; font-weight: bold;")
            self.statusJoystick.setText("手柄: 键盘模式")

    @Slot(dict)
    def _slot_overcurrent(self, status: dict) -> None:
        self._overcurrent_status = status
        if status.get("event") == "enter":
            self.lblOcStatus.setText("⚠ 过流")
            self.lblOcStatus.setStyleSheet(S_WARN)
        elif status.get("event") == "exit":
            self.lblOcStatus.setText("● 正常")
            self.lblOcStatus.setStyleSheet(S_NORMAL)

    # ════════════════════════════════════════════════
    #  控件内容刷新
    # ════════════════════════════════════════════════

    def _refresh_sensor(self, d: SensorData) -> None:
        self.lblTempVal.setText(f"{d.temperature:.1f} °C")
        self.lblCurrentVal.setText(f"{d.current:.2f} A")
        if d.water_ingress:
            self.lblWaterVal.setText("⚠ 进水告警!")
            self.lblWaterVal.setStyleSheet(S_WARN)
        else:
            self.lblWaterVal.setText("正常")
            self.lblWaterVal.setStyleSheet(S_NORMAL)

    def _refresh_control(self, cs: ControlState) -> None:
        self.lblCtrlYVal.setText(f"{cs.thrust_y:.2f}")
        self.lblCtrlXVal.setText(f"{cs.thrust_x:.2f}")
        self.lblCtrlZVal.setText(f"{cs.thrust_z:.2f}")
        self.lblCtrlYawVal.setText(f"{cs.yaw_torque:.2f}")

        # 运动模式
        mode_map = {
            SpeedMode.SLOW:   (self.lblModeSlow,   "#0f0"),
            SpeedMode.MEDIUM: (self.lblModeMedium, "#f80"),
            SpeedMode.FAST:   (self.lblModeFast,   "#f00"),
        }
        for mode, (lbl, color) in mode_map.items():
            prefix = "●" if cs.mode == mode else "○"
            lbl.setText(f"{prefix} {MODE_NAMES[mode]}")
            lbl.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")

        # 夹爪
        if cs.claw_open:
            self.lblClaw.setText("张开")
            self.lblClaw.setStyleSheet("color: #0f0; font-size: 14px; font-weight: bold;")
        else:
            self.lblClaw.setText("夹紧")
            self.lblClaw.setStyleSheet(S_YELLOW + "; font-size: 14px;")

    # ── 键盘映射（从 config.ini 加载）──
    @staticmethod
    def _resolve_key_name(name: str):
        """
        从 config.ini 的按键名动态解析为 (Qt.Key, pygame.K) 元组。
        优先查 _KEY_OVERRIDE 覆盖表，否则通过反射从 Qt/pygame 实时获取。
        """
        if not name:
            return None

        override = _KEY_OVERRIDE.get(name)
        if override:
            qt_attr, pg_attr = override
            try:
                qt_key = getattr(Qt.Key, qt_attr)
            except AttributeError:
                return None
            try:
                pg_key = getattr(pygame, pg_attr)
            except AttributeError:
                return None
            return (qt_key, pg_key)

        # 动态解析：Qt.Key.Key_<name>
        try:
            qt_key = getattr(Qt.Key, f"Key_{name}")
        except AttributeError:
            return None

        # 动态解析：pygame.K_<name>（先小写，再大写）
        try:
            pg_key = getattr(pygame, f"K_{name.lower()}")
        except AttributeError:
            try:
                pg_key = getattr(pygame, f"K_{name.upper()}")
            except AttributeError:
                return None

        return (qt_key, pg_key)

    def _load_key_mapping(self) -> None:
        """从 config.ini 读取所有键盘映射，构建 Qt→pygame 键码表"""
        cfg = configparser.ConfigParser()
        cfg.read(_DEFAULT_CONFIG, encoding="utf-8")

        self._qt_to_pygame: dict[int, int] = {}
        if not cfg.has_section("keyboard"):
            return

        # 所有配置键名（全部转发到 pygame）
        cfg_keys = [
            "key_forward", "key_backward", "key_yaw_left", "key_yaw_right",
            "key_strafe_left", "key_strafe_right",
            "key_ascend", "key_descend",
            "key_mode_toggle", "key_mode_reverse",
            "key_claw_open", "key_claw_close",
            "key_snapshot", "key_record",
        ]
        for name in cfg_keys:
            val = cfg.get("keyboard", name, fallback="")
            resolved = self._resolve_key_name(val)
            if resolved is not None:
                qt_key, pg_key = resolved
                self._qt_to_pygame[qt_key.value] = pg_key

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        pg_key = self._qt_to_pygame.get(int(event.key()))
        if pg_key is not None:
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pg_key))
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        pg_key = self._qt_to_pygame.get(int(event.key()))
        if pg_key is not None:
            pygame.event.post(pygame.event.Event(pygame.KEYUP, key=pg_key))
            event.accept()
            return
        super().keyReleaseEvent(event)

    # ── 关闭 ──
    def closeEvent(self, event) -> None:
        self._ui_timer.stop()
        super().closeEvent(event)
