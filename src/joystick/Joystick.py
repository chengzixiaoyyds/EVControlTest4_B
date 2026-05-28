"""
手柄控制模块 —— 读取手柄/键盘输入，映射为 ROV 控制量。

依赖: pygame

摇杆映射（参考《Mini ROV 技术手册》附录 A~C）：

  手柄操作              → ROV 动作          → 输出字段
  ─────────────────────────────────────────────────────
  左摇杆 前推 / 后拉     → 前进 / 后退       → thrust_y
  左摇杆 右推 / 左推     → 顺时针 / 逆时针    → yaw_torque
  右摇杆 右推 / 左推     → 右移 / 左移        → thrust_x
  右摇杆 前推 / 后拉     → 上浮 / 下潜        → thrust_z
  X 键                   → 运动模式轮换       → mode
  LB / RB               → 夹爪张开 / 夹紧    → claw_state

模式档位：
  SLOW   (30%)  — 精确定位
  MEDIUM (60%)  — 一般巡检
  FAST   (100%) — 快速移动
"""

import configparser
import os
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional

import pygame

# ───────── 路径 ─────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_CONFIG = os.path.join(_BASE_DIR, "config", "config.ini")


# ════════════════════════════════════════════════════════
#  数据结构
# ════════════════════════════════════════════════════════

class SpeedMode(IntEnum):
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
    """单帧控制量，可直接传给 SerialComm.build_data_frame()"""
    thrust_y: float = 0.0       # Y 推力 (N)，前进为正
    thrust_x: float = 0.0       # X 推力 (N)，右移为正（预留）
    thrust_z: float = 0.0       # Z 推力 (N)，下潜为正
    yaw_torque: float = 0.0     # Yaw 扭矩 (N·m)，顺时针为正
    arm_angle: int = 0x00        # 机械臂角度 0x00夹紧~0x80松开
    mode: SpeedMode = SpeedMode.SLOW
    claw_open: bool = False     # 夹爪是否张开


# ════════════════════════════════════════════════════════
#  手柄驱动类
# ════════════════════════════════════════════════════════

class JoystickController:
    """手柄 / 键盘 控制器，每一帧调用 update() 获取最新 ControlState"""

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

    # ── 默认轴配置（每轴独立） ──
    # {name: {"axis": int, "max": float, "deadzone": float}}
    _axis_cfg = {
        "y":   {"axis": 1, "max": 5000.0,  "deadzone": 0.05},
        "x":   {"axis": 2, "max": 6000.0,  "deadzone": 0.05},
        "z":   {"axis": 3, "max": 6000.0,  "deadzone": 0.05},
        "yaw": {"axis": 0, "max": 1000.0,  "deadzone": 0.05},
    }

    ARM_OPEN = 0x80     # 0x80 松开
    ARM_CLOSE = 0x00     # 0x00 夹紧

    # ── 长按判定 ──
    LONG_PRESS_MS = 400       # 超过此时间视为长按

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = config_path or _DEFAULT_CONFIG
        self._joystick: "pygame.joystick.JoystickType | None" = None
        self._has_joystick = False

        # 状态
        self._mode = SpeedMode.SLOW
        self._claw_open = False
        self._arm_angle = self.ARM_CLOSE

        # 模式切换键状态
        self._mode_key_pressed_time: Optional[float] = None
        self._mode_key_handled = False
        self._mode_reverse_pressed_time: Optional[float] = None
        self._mode_reverse_handled = False

        # 夹爪按键下降沿
        self._lb_prev = False
        self._rb_prev = False
        self._key_claw_open_prev = False
        self._key_claw_close_prev = False

        # 截图/录像快捷键下降沿
        self._key_snapshot_prev = False
        self._key_record_prev = False

        # 快捷键回调（由 main.py 设置）
        self.on_snapshot: Optional[Callable[[], None]] = None
        self.on_record_toggle: Optional[Callable[[], None]] = None

        # 键盘轴状态（无手柄时使用）
        self._key_axes = {"y": 0.0, "x": 0.0, "z": 0.0, "yaw": 0.0}

        # 键盘按键追踪（基于 pygame 事件，兼容 Qt 转发）
        self._key_state: dict[int, bool] = {}

        # 加载配置
        self._load_config()

        # 初始化 pygame
        self._init_pygame()

    def _load_config(self) -> None:
        """读取 config.ini 覆盖默认值"""
        cfg = configparser.ConfigParser()
        if not os.path.exists(self._config_path):
            return
        cfg.read(self._config_path, encoding="utf-8")

        # ── 手柄轴映射（每轴独立节） ──
        for name in ("x", "y", "z", "yaw"):
            if cfg.has_section(name):
                self._axis_cfg[name]["axis"] = cfg.getint(name, "axis", fallback=self._axis_cfg[name]["axis"])
                self._axis_cfg[name]["max"] = cfg.getfloat(name, "max", fallback=self._axis_cfg[name]["max"])
                self._axis_cfg[name]["deadzone"] = cfg.getfloat(name, "deadzone", fallback=self._axis_cfg[name]["deadzone"])

        # ── 手柄通用设置 ──
        if cfg.has_section("joystick"):
            self.LONG_PRESS_MS = cfg.getint("joystick", "mode_long_press", fallback=self.LONG_PRESS_MS)
            self.BTN_X = cfg.getint("joystick", "btn_mode", fallback=self.BTN_X)
            self.BTN_LB = cfg.getint("joystick", "btn_claw_open", fallback=self.BTN_LB)
            self.BTN_RB = cfg.getint("joystick", "btn_claw_close", fallback=self.BTN_RB)

        # ── 键盘映射 ──
        if cfg.has_section("keyboard"):
            self.KEY_FORWARD = self._key_from_cfg(cfg, "keyboard", "key_forward", self.KEY_FORWARD)
            self.KEY_BACKWARD = self._key_from_cfg(cfg, "keyboard", "key_backward", self.KEY_BACKWARD)
            self.KEY_YAW_LEFT = self._key_from_cfg(cfg, "keyboard", "key_yaw_left", self.KEY_YAW_LEFT)
            self.KEY_YAW_RIGHT = self._key_from_cfg(cfg, "keyboard", "key_yaw_right", self.KEY_YAW_RIGHT)
            self.KEY_STRAFE_LEFT = self._key_from_cfg(cfg, "keyboard", "key_strafe_left", self.KEY_STRAFE_LEFT)
            self.KEY_STRAFE_RIGHT = self._key_from_cfg(cfg, "keyboard", "key_strafe_right", self.KEY_STRAFE_RIGHT)
            self.KEY_ASCEND = self._key_from_cfg(cfg, "keyboard", "key_ascend", self.KEY_ASCEND)
            self.KEY_DESCEND = self._key_from_cfg(cfg, "keyboard", "key_descend", self.KEY_DESCEND)
            self.KEY_MODE_TOGGLE = self._key_from_cfg(cfg, "keyboard", "key_mode_toggle", self.KEY_MODE_TOGGLE)
            self.KEY_MODE_REVERSE = self._key_from_cfg(cfg, "keyboard", "key_mode_reverse", self.KEY_MODE_REVERSE)
            self.KEY_CLAW_OPEN = self._key_from_cfg(cfg, "keyboard", "key_claw_open", self.KEY_CLAW_OPEN)
            self.KEY_CLAW_CLOSE = self._key_from_cfg(cfg, "keyboard", "key_claw_close", self.KEY_CLAW_CLOSE)
            self.KEY_SNAPSHOT = self._key_from_cfg(cfg, "keyboard", "key_snapshot", self.KEY_SNAPSHOT)
            self.KEY_RECORD = self._key_from_cfg(cfg, "keyboard", "key_record", self.KEY_RECORD)

        # ── 速度档位 ──
        if cfg.has_section("speed_modes"):
            for i in range(3):
                rate = cfg.getfloat("speed_modes", f"mode{i}_rate", fallback=list(MODE_RATES.values())[i])
                name = cfg.get("speed_modes", f"mode{i}_name", fallback=list(MODE_NAMES.values())[i])
                mode = SpeedMode(i)
                MODE_RATES[mode] = rate
                MODE_NAMES[mode] = name

    @staticmethod
    def _key_from_cfg(cfg: configparser.ConfigParser, section: str, key: str, default: int) -> int:
        """将配置中的按键名转为 pygame 键码"""
        name = cfg.get(section, key, fallback="")
        if not name:
            return default
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

    @property
    def mode(self) -> SpeedMode:
        return self._mode

    @property
    def mode_name(self) -> str:
        return MODE_NAMES.get(self._mode, "UNKNOWN")

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
        rate = MODE_RATES[self._mode]

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

    # ── 手柄按键 ──
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

    # ── 键盘 ──
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

    def _handle_keyboard_buttons(self) -> None:
        """处理键盘按键（模式切换、夹爪）—— 基于事件追踪"""
        ks = self._key_state

        # 模式切换 — 支持独立 toggle / reverse 键
        if self.KEY_MODE_TOGGLE == self.KEY_MODE_REVERSE:
            # 同键：短按正向，长按反向
            self._handle_mode_key(
                ks.get(self.KEY_MODE_TOGGLE, False), "_mode_key_pressed_time", "_mode_key_handled"
            )
        else:
            # 不同键：各自下降沿触发
            toggle_now = ks.get(self.KEY_MODE_TOGGLE, False)
            reverse_now = ks.get(self.KEY_MODE_REVERSE, False)

            self._handle_mode_key(
                toggle_now, "_mode_key_pressed_time", "_mode_key_handled"
            )
            # reverse 键独立处理：下降沿反向轮换
            now = time.time()
            if reverse_now:
                if self._mode_reverse_pressed_time is None:
                    self._mode_reverse_pressed_time = now
                    self._mode_reverse_handled = False
                # 独立键：按下即触发，无长按逻辑
                if not self._mode_reverse_handled:
                    self._mode = SpeedMode((self._mode.value - 1) % 3)
                    self._mode_reverse_handled = True
            else:
                self._mode_reverse_pressed_time = None
                self._mode_reverse_handled = False

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
