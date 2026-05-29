"""
输入模块 —— 手柄/键盘 → ROV 控制量映射。

双输入源自动切换: 检测到物理手柄则用手柄，否则键盘模拟。
键盘事件由 MainWindow 捕获 → KeyBridge 转发为 pygame 事件 → 本模块统一处理。

输出: ControlState (thrust_y/x/z, yaw_torque, arm_angle, mode, claw_state)
"""

import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable, Optional

import pygame


# ════════════════════════════════════════════════════════
#  数据结构
# ════════════════════════════════════════════════════════

class SpeedMode(IntEnum):
    """三档速度模式，影响控制量的倍率系数"""
    SLOW = 0
    MEDIUM = 1
    FAST = 2


MODE_NAMES = {
    SpeedMode.SLOW: "SLOW",
    SpeedMode.MEDIUM: "MEDIUM",
    SpeedMode.FAST: "FAST",
}

MODE_RATES = {
    SpeedMode.SLOW: 0.30,
    SpeedMode.MEDIUM: 0.60,
    SpeedMode.FAST: 1.00,
}


@dataclass
class ControlState:
    """
    单帧控制指令，可直接传给 SerialComm.build_data_frame()。

    坐标系 (WND 右手系):
      thrust_y: 前进+   thrust_x: 右移+   thrust_z: 下潜+
      yaw_torque: 顺时针+
    """
    thrust_y: float = 0.0       # Y 推力 (N)，前进为正
    thrust_x: float = 0.0       # X 推力 (N)，右移为正（预留）
    thrust_z: float = 0.0       # Z 推力 (N)，下潜为正
    yaw_torque: float = 0.0     # Yaw 扭矩 (N·m)，顺时针为正
    arm_angle: int = 0x00        # 机械臂角度 0x00夹紧~0x80松开
    mode: SpeedMode = SpeedMode.SLOW
    mode_name: str = "SLOW"      # 当前模式名称（由 JoystickController 填充）
    claw_open: bool = False     # 夹爪是否张开


# ════════════════════════════════════════════════════════
#  手柄驱动类
# ════════════════════════════════════════════════════════

class JoystickController:
    """
    输入统一层 —— 屏蔽手柄/键盘差异，输出标准 ControlState。

    手柄模式: 读取 pygame 摇杆轴值 + 按钮
    键盘模式: 接收 Qt 转发事件，按下即满量程（无渐变）

    模式切换: X 键短按正向轮换 (SLOW→MEDIUM→FAST)，长按反向
    """

    # ── 默认轴映射（pygame 轴索引） ──
    AXIS_LX = 0          # 左摇杆 X
    AXIS_LY = 1          # 左摇杆 Y
    AXIS_RX = 2          # 右摇杆 X
    AXIS_RY = 3          # 右摇杆 Y

    # ── 默认按钮映射（Xbox 控制器） ──
    BTN_X = 2            # X 键 — 模式切换
    BTN_LB = 4           # 左肩键 — 张开夹爪
    BTN_RB = 5           # 右肩键 — 夹紧夹爪

    # ── 默认键盘映射 ──
    KEY_FORWARD = pygame.K_w         # 前进
    KEY_BACKWARD = pygame.K_s        # 后退
    KEY_YAW_LEFT = pygame.K_a        # 逆时针旋转（等效左摇杆左推）
    KEY_YAW_RIGHT = pygame.K_d       # 顺时针旋转（等效左摇杆右推）
    KEY_STRAFE_LEFT = pygame.K_LEFT  # 左移（等效右摇杆左推）
    KEY_STRAFE_RIGHT = pygame.K_RIGHT# 右移（等效右摇杆右推）
    KEY_ASCEND = pygame.K_UP         # 上浮
    KEY_DESCEND = pygame.K_DOWN      # 下潜
    KEY_MODE_TOGGLE = pygame.K_x
    KEY_MODE_REVERSE = pygame.K_x      # 与 toggle 同键时：短按正向，长按反向
    KEY_CLAW_OPEN = pygame.K_q
    KEY_CLAW_CLOSE = pygame.K_e
    KEY_SNAPSHOT = pygame.K_p        # 截图
    KEY_RECORD = pygame.K_r          # 录像

    ARM_OPEN = 0x40     # 0x40 松开
    ARM_CLOSE = 0x00     # 0x00 夹紧

    # ── 长按判定 ──
    LONG_PRESS_MS = 400       # 超过此时间视为长按

    def __init__(self, keyboard_cfg: dict, joystick_cfg: dict, axis_cfg: dict, speed_cfg: dict):
        """
        所有配置由 AppCore 统一加载后传入，本模块不再读取 config.ini。

        :param keyboard_cfg: {"key_forward": "W", "key_backward": "S", ...}
        :param joystick_cfg: {"mode_long_press": "400", "btn_mode": "2", ...}
        :param axis_cfg:     {"x": {"max": "6000.0", "axis": "2", "deadzone": "0.05"}, ...}
        :param speed_cfg:    {"mode0_rate": "0.30", "mode0_name": "SLOW", ...}
        """
        self._joystick: "pygame.joystick.JoystickType | None" = None
        self._has_joystick = False

        # ── 轴配置 ──
        self._axis_cfg = {
            "y":   {"axis": 1, "max": 5000.0,  "deadzone": 0.05},
            "x":   {"axis": 2, "max": 6000.0,  "deadzone": 0.05},
            "z":   {"axis": 3, "max": 6000.0,  "deadzone": 0.05},
            "yaw": {"axis": 0, "max": 1000.0,  "deadzone": 0.05},
        }

        # 状态
        self._mode = SpeedMode.SLOW
        self._claw_open = False
        self._arm_angle = self.ARM_CLOSE

        # 速度档位（实例级，从 config.ini 加载，初始使用模块默认值）
        self._mode_names = dict(MODE_NAMES)
        self._mode_rates = dict(MODE_RATES)

        # 模式切换键状态（同键时使用 _handle_mode_key 的长按判定）
        self._mode_key_pressed_time: Optional[float] = None
        self._mode_key_handled = False
        # 独立 toggle/reverse 键的边沿检测
        self._mode_toggle_prev = False
        self._mode_reverse_prev = False

        # 夹爪按键下降沿
        self._lb_prev = False
        self._rb_prev = False
        self._key_claw_open_prev = False
        self._key_claw_close_prev = False

        # 截图/录像快捷键下降沿
        self._key_snapshot_prev = False
        self._key_record_prev = False

        # 快捷键回调（由 AppCore.start() 内部绑定）
        self.on_snapshot: Optional[Callable[[], Any]] = None
        self.on_record_toggle: Optional[Callable[[], Any]] = None

        # 键盘轴状态（无手柄时使用）
        self._key_axes = {"y": 0.0, "x": 0.0, "z": 0.0, "yaw": 0.0}

        # 键盘按键追踪（基于 pygame 事件，兼容 Qt 转发）
        self._key_state: dict[int, bool] = {}

        # 加载配置（从 AppCore 传入的 dict）
        self._apply_config(keyboard_cfg, joystick_cfg, axis_cfg, speed_cfg)

        # 初始化 pygame
        self._init_pygame()

    # ── 配置应用（由 AppCore 传入 dict，不再直接读取文件）──
    def _apply_config(self, keyboard_cfg: dict, joystick_cfg: dict, axis_cfg: dict, speed_cfg: dict) -> None:
        # ── 手柄轴映射 ──
        for name in ("x", "y", "z", "yaw"):
            sec = axis_cfg.get(name, {})
            if sec:
                if "axis" in sec:
                    self._axis_cfg[name]["axis"] = int(sec["axis"])
                if "max" in sec:
                    self._axis_cfg[name]["max"] = float(sec["max"])
                if "deadzone" in sec:
                    self._axis_cfg[name]["deadzone"] = float(sec["deadzone"])

        # ── 手柄通用设置 ──
        if joystick_cfg:
            if "mode_long_press" in joystick_cfg:
                self.LONG_PRESS_MS = int(joystick_cfg["mode_long_press"])
            if "btn_mode" in joystick_cfg:
                self.BTN_X = int(joystick_cfg["btn_mode"])
            if "btn_claw_open" in joystick_cfg:
                self.BTN_LB = int(joystick_cfg["btn_claw_open"])
            if "btn_claw_close" in joystick_cfg:
                self.BTN_RB = int(joystick_cfg["btn_claw_close"])

        # ── 键盘映射 ──
        if keyboard_cfg:
            self.KEY_FORWARD = self._key_from_dict(keyboard_cfg, "key_forward", self.KEY_FORWARD)
            self.KEY_BACKWARD = self._key_from_dict(keyboard_cfg, "key_backward", self.KEY_BACKWARD)
            self.KEY_YAW_LEFT = self._key_from_dict(keyboard_cfg, "key_yaw_left", self.KEY_YAW_LEFT)
            self.KEY_YAW_RIGHT = self._key_from_dict(keyboard_cfg, "key_yaw_right", self.KEY_YAW_RIGHT)
            self.KEY_STRAFE_LEFT = self._key_from_dict(keyboard_cfg, "key_strafe_left", self.KEY_STRAFE_LEFT)
            self.KEY_STRAFE_RIGHT = self._key_from_dict(keyboard_cfg, "key_strafe_right", self.KEY_STRAFE_RIGHT)
            self.KEY_ASCEND = self._key_from_dict(keyboard_cfg, "key_ascend", self.KEY_ASCEND)
            self.KEY_DESCEND = self._key_from_dict(keyboard_cfg, "key_descend", self.KEY_DESCEND)
            self.KEY_MODE_TOGGLE = self._key_from_dict(keyboard_cfg, "key_mode_toggle", self.KEY_MODE_TOGGLE)
            self.KEY_MODE_REVERSE = self._key_from_dict(keyboard_cfg, "key_mode_reverse", self.KEY_MODE_REVERSE)
            self.KEY_CLAW_OPEN = self._key_from_dict(keyboard_cfg, "key_claw_open", self.KEY_CLAW_OPEN)
            self.KEY_CLAW_CLOSE = self._key_from_dict(keyboard_cfg, "key_claw_close", self.KEY_CLAW_CLOSE)
            self.KEY_SNAPSHOT = self._key_from_dict(keyboard_cfg, "key_snapshot", self.KEY_SNAPSHOT)
            self.KEY_RECORD = self._key_from_dict(keyboard_cfg, "key_record", self.KEY_RECORD)

        # ── 速度档位 ──
        if speed_cfg:
            for i in range(3):
                rate = float(speed_cfg.get(f"mode{i}_rate", list(self._mode_rates.values())[i]))
                name = speed_cfg.get(f"mode{i}_name", list(self._mode_names.values())[i])
                mode = SpeedMode(i)
                self._mode_rates[mode] = rate
                self._mode_names[mode] = name

    # ── pygame 键名覆盖（pygame 命名不遵循 K_<name> 规则时使用）──
    _PG_KEY_OVERRIDE: dict[str, str] = {
        "Shift":        "K_LSHIFT",        # pygame 只有 K_LSHIFT/K_RSHIFT
        "Control":      "K_LCTRL",         # pygame 只有 K_LCTRL/K_RCTRL
        "Alt":          "K_LALT",          # pygame 只有 K_LALT/K_RALT
        "Meta":         "K_LMETA",         # pygame 只有 K_LMETA/K_RMETA
        "Enter":        "K_RETURN",        # pygame 用 K_RETURN
        "Equal":        "K_EQUALS",        # pygame 用 K_EQUALS
        "BracketLeft":  "K_LEFTBRACKET",
        "BracketRight": "K_RIGHTBRACKET",
        "Backquote":    "K_BACKQUOTE",
        "QuoteDbl":     "K_QUOTEDBL",
    }

    @staticmethod
    def _key_from_dict(keyboard_cfg: dict, key: str, default: int) -> int:
        """从键盘配置字典中解析按键名 → pygame 键码"""
        name = keyboard_cfg.get(key, "")
        if not name:
            return default

        # 1) 覆盖表优先
        override = JoystickController._PG_KEY_OVERRIDE.get(name)
        if override:
            try:
                return getattr(pygame, override)
            except AttributeError:
                return default

        # 2) 动态反射：先小写再大写
        try:
            return getattr(pygame, f"K_{name.lower()}")
        except AttributeError:
            try:
                return getattr(pygame, f"K_{name.upper()}")
            except AttributeError:
                return default

    # ── 初始化 ──
    def _init_pygame(self) -> None:
        """初始化 pygame 和手柄"""
        pygame.init()
        pygame.joystick.init()

        count = pygame.joystick.get_count()
        if count > 0:
            joy = pygame.joystick.Joystick(0)
            joy.init()
            self._joystick = joy
            self._has_joystick = True
            print(f"[Joystick] 已连接: {joy.get_name()}")
        else:
            self._has_joystick = False
            print("[Joystick] 未检测到手柄，使用键盘控制")

    # ── 属性 ──
    @property
    def has_joystick(self) -> bool:
        return self._has_joystick

    def refresh_joystick(self) -> bool:
        """
        重新检测手柄连接状态（支持热插拔）。
        :return: 当前是否有手柄连接
        """
        count = pygame.joystick.get_count()
        if count > 0:
            if not self._has_joystick:
                # 新插入手柄
                try:
                    joy = pygame.joystick.Joystick(0)
                    joy.init()
                    self._joystick = joy
                    self._has_joystick = True
                    print(f"[Joystick] 检测到手柄插入: {joy.get_name()}")
                except pygame.error:
                    self._has_joystick = False
                    self._joystick = None
            # 已有手柄，保持
        else:
            if self._has_joystick:
                # 手柄拔出
                if self._joystick:
                    try:
                        self._joystick.quit()
                    except pygame.error:
                        pass
                self._joystick = None
                self._has_joystick = False
                print("[Joystick] 手柄已拔出，切换到键盘模式")
        return self._has_joystick

    @property
    def mode(self) -> SpeedMode:
        return self._mode

    @property
    def mode_names(self) -> dict:
        """所有速度模式的名称映射 {SpeedMode: str}，供 UI 读取"""
        return dict(self._mode_names)

    @property
    def mode_name(self) -> str:
        return self._mode_names.get(self._mode, "UNKNOWN")

    @property
    def claw_open(self) -> bool:
        return self._claw_open

    # ── 主更新 ──
    def update(self) -> ControlState:
        """
        每帧调用一次，读取输入并返回 ControlState。
        调用方应按固定频率调用（如 125 Hz）。
        """
        pygame.event.pump()

        # 从事件队列更新键盘状态（兼容 Qt 转发的 pygame 事件）
        for event in pygame.event.get([pygame.KEYDOWN, pygame.KEYUP]):
            if event.type == pygame.KEYDOWN:
                self._key_state[event.key] = True
            elif event.type == pygame.KEYUP:
                self._key_state[event.key] = False

        cfg = self._axis_cfg

        # 读取轴值
        if self._has_joystick:
            ly_raw = -self._get_axis(cfg["y"]["axis"])    # Xbox: 前推=-1，取反后前进=+1
            lx_raw = self._get_axis(cfg["yaw"]["axis"])
            rx_raw = self._get_axis(cfg["x"]["axis"])
            ry_raw = self._get_axis(cfg["z"]["axis"])      # 后拉=+1 → 下潜=+1
            self._handle_joystick_buttons()
        else:
            self._handle_keyboard_axes()
            ly_raw = self._key_axes["y"]
            lx_raw = self._key_axes["yaw"]
            rx_raw = self._key_axes["x"]
            ry_raw = self._key_axes["z"]
            self._handle_keyboard_buttons()

        # 死区（每轴独立）
        ly = self._deadzone(ly_raw, cfg["y"]["deadzone"])
        lx = self._deadzone(lx_raw, cfg["yaw"]["deadzone"])
        rx = self._deadzone(rx_raw, cfg["x"]["deadzone"])
        ry = self._deadzone(ry_raw, cfg["z"]["deadzone"])

        # 速度系数
        rate = self._mode_rates[self._mode]

        # 映射到 ROV 控制量（WND 坐标系）
        # max 值的符号决定方向：正值 = 摇杆正向→ROV正向
        thrust_y = ly * cfg["y"]["max"] * rate
        thrust_x = rx * cfg["x"]["max"] * rate
        thrust_z = ry * cfg["z"]["max"] * rate
        yaw_torque = lx * cfg["yaw"]["max"] * rate

        return ControlState(
            thrust_y=thrust_y,
            thrust_x=thrust_x,
            thrust_z=thrust_z,
            yaw_torque=yaw_torque,
            arm_angle=self._arm_angle,
            mode=self._mode,
            mode_name=self._mode_names.get(self._mode, "UNKNOWN"),
            claw_open=self._claw_open,
        )

    # ── 轴读取 ──
    def _get_axis(self, axis_id: int) -> float:
        """读取手柄轴值，范围为 [-1, 1]"""
        joy = self._joystick
        if joy is None or axis_id >= joy.get_numaxes():
            return 0.0
        val = joy.get_axis(axis_id)
        return max(-1.0, min(1.0, val))

    @staticmethod
    def _deadzone(value: float, threshold: float) -> float:
        """死区滤波"""
        return 0.0 if abs(value) < threshold else value

    # ── 模式切换（通用） ──
    def _handle_mode_key(self, key_pressed: bool, pressed_time_attr: str, handled_attr: str) -> None:
        """
        处理模式切换键：短按正向轮换，长按反向轮换。
        当 toggle 和 reverse 是同键时，toggle 调用此方法并传入 reverse 的状态变量。
        """
        now = time.time()
        pt = getattr(self, pressed_time_attr)  # 按下时刻
        hd = getattr(self, handled_attr)       # 是否已处理长按

        if key_pressed:
            if pt is None:
                setattr(self, pressed_time_attr, now)
                setattr(self, handled_attr, False)
            elif not hd:
                elapsed = (now - pt) * 1000
                if elapsed >= self.LONG_PRESS_MS:
                    self._mode = SpeedMode((self._mode.value - 1) % 3)
                    setattr(self, handled_attr, True)
        else:
            if pt is not None and not hd:
                self._mode = SpeedMode((self._mode.value + 1) % 3)
            setattr(self, pressed_time_attr, None)
            setattr(self, handled_attr, False)

    # ── 手柄按键处理（下降沿触发）──
    def _handle_joystick_buttons(self) -> None:
        """处理手柄按键（X 模式切换、LB/RB 夹爪）"""
        joy = self._joystick
        if joy is None:
            return
        n_buttons = joy.get_numbuttons()

        def get_btn(idx: int) -> bool:
            return idx < n_buttons and joy.get_button(idx)

        # X 键 — 模式切换（短按正向，长按反向）
        self._handle_mode_key(
            get_btn(self.BTN_X), "_mode_key_pressed_time", "_mode_key_handled"
        )

        # LB — 张开夹爪（下降沿）
        lb_now = get_btn(self.BTN_LB)
        if self._lb_prev and not lb_now:
            self._claw_open = True
            self._arm_angle = self.ARM_OPEN
        self._lb_prev = lb_now

        # RB — 夹紧夹爪（下降沿）
        rb_now = get_btn(self.BTN_RB)
        if self._rb_prev and not rb_now:
            self._claw_open = False
            self._arm_angle = self.ARM_CLOSE
        self._rb_prev = rb_now

    # ── 键盘轴模拟（按下即满量程，无渐变）──
    def _handle_keyboard_axes(self) -> None:
        """读取键盘状态（基于事件追踪），模拟摇杆轴 —— 按下即输出最大值"""
        ks = self._key_state

        self._key_axes["y"] = 0.0
        self._key_axes["x"] = 0.0
        self._key_axes["z"] = 0.0
        self._key_axes["yaw"] = 0.0

        if ks.get(self.KEY_FORWARD, False):      self._key_axes["y"] += 1.0
        if ks.get(self.KEY_BACKWARD, False):     self._key_axes["y"] -= 1.0
        if ks.get(self.KEY_STRAFE_RIGHT, False): self._key_axes["x"] += 1.0
        if ks.get(self.KEY_STRAFE_LEFT, False):  self._key_axes["x"] -= 1.0
        if ks.get(self.KEY_DESCEND, False):      self._key_axes["z"] += 1.0
        if ks.get(self.KEY_ASCEND, False):       self._key_axes["z"] -= 1.0
        if ks.get(self.KEY_YAW_RIGHT, False):    self._key_axes["yaw"] += 1.0
        if ks.get(self.KEY_YAW_LEFT, False):     self._key_axes["yaw"] -= 1.0

    # ── 键盘按键处理（模式切换、夹爪、截图、录像，基于下降沿）──
    def _handle_keyboard_buttons(self) -> None:
        ks = self._key_state

        # 模式切换 — 支持独立 toggle / reverse 键
        if self.KEY_MODE_TOGGLE == self.KEY_MODE_REVERSE:
            # 同键：短按正向，长按反向
            self._handle_mode_key(
                ks.get(self.KEY_MODE_TOGGLE, False), "_mode_key_pressed_time", "_mode_key_handled"
            )
        else:
            # 不同键：各自下降沿触发，toggle 仅正向轮换（无长按反转）
            toggle_now = ks.get(self.KEY_MODE_TOGGLE, False)
            reverse_now = ks.get(self.KEY_MODE_REVERSE, False)

            # toggle 键：下降沿正向轮换
            if self._mode_toggle_prev and not toggle_now:
                self._mode = SpeedMode((self._mode.value + 1) % 3)
            self._mode_toggle_prev = toggle_now

            # reverse 键：下降沿反向轮换
            if self._mode_reverse_prev and not reverse_now:
                self._mode = SpeedMode((self._mode.value - 1) % 3)
            self._mode_reverse_prev = reverse_now

        # Q — 张开夹爪（下降沿）
        q_now = ks.get(self.KEY_CLAW_OPEN, False)
        if self._key_claw_open_prev and not q_now:
            self._claw_open = True
            self._arm_angle = self.ARM_OPEN
        self._key_claw_open_prev = q_now

        # E — 夹紧夹爪（下降沿）
        e_now = ks.get(self.KEY_CLAW_CLOSE, False)
        if self._key_claw_close_prev and not e_now:
            self._claw_open = False
            self._arm_angle = self.ARM_CLOSE
        self._key_claw_close_prev = e_now

        # P — 截图（下降沿）
        p_now = ks.get(self.KEY_SNAPSHOT, False)
        if self._key_snapshot_prev and not p_now:
            if self.on_snapshot:
                self.on_snapshot()
        self._key_snapshot_prev = p_now

        # R — 录像（下降沿）
        r_now = ks.get(self.KEY_RECORD, False)
        if self._key_record_prev and not r_now:
            if self.on_record_toggle:
                self.on_record_toggle()
        self._key_record_prev = r_now

    # ── 资源释放 ──
    def close(self) -> None:
        """释放手柄和 pygame 资源"""
        joy = self._joystick
        if joy is not None:
            joy.quit()
        pygame.joystick.quit()
        pygame.quit()
