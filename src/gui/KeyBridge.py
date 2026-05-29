"""
键盘桥接 —— Qt KeyEvent → pygame 事件转发。

存在原因: MainWindow 用 Qt 捕获按键，JoystickController 用 pygame 处理输入，
两者不互通。本模块负责翻译。

按键名解析: 覆盖表优先（处理命名例外），回退到动态反射（Key_X → K_x）。
"""

from typing import Optional

import pygame
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

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


class KeyBridge:
    """Qt → pygame 翻译器 —— 接收键盘配置 dict，建立键码映射表"""

    def __init__(self, keyboard_cfg: dict):
        """
        :param keyboard_cfg: 键盘映射字典，如 {"key_forward": "W", "key_backward": "S", ...}
                             由 AppCore.keyboard_config 统一提供
        """
        self._qt_to_pygame: dict[int, int] = {}
        self._load_mapping(keyboard_cfg)

    # ── 公开接口 ──

    def handle_key_press(self, event: QKeyEvent) -> bool:
        """
        处理 Qt 按键按下事件，转发到 pygame。
        :return: True 表示事件已被处理（应调用 event.accept()）
        """
        if event.isAutoRepeat():
            return False
        return self._post_pygame_event(event, pygame.KEYDOWN)

    def handle_key_release(self, event: QKeyEvent) -> bool:
        """
        处理 Qt 按键释放事件，转发到 pygame。
        :return: True 表示事件已被处理（应调用 event.accept()）
        """
        if event.isAutoRepeat():
            return False
        return self._post_pygame_event(event, pygame.KEYUP)

    # ── 内部实现 ──

    def _post_pygame_event(self, event: QKeyEvent, event_type: int) -> bool:
        """将 Qt 按键事件投递为 pygame 事件"""
        pg_key = self._qt_to_pygame.get(int(event.key()))
        if pg_key is not None:
            pygame.event.post(pygame.event.Event(event_type, key=pg_key))
            return True
        return False

    def _load_mapping(self, keyboard_cfg: dict) -> None:
        """从键盘配置字典加载 Qt→pygame 键码映射，遍历全部配置值"""
        self._qt_to_pygame.clear()
        if not keyboard_cfg:
            return

        for key_name in set(keyboard_cfg.values()):
            resolved = self._resolve_key_pair(key_name)
            if resolved is not None:
                qt_key, pg_key = resolved
                self._qt_to_pygame[qt_key.value] = pg_key

    @staticmethod
    def _resolve_key_pair(name: str) -> Optional[tuple]:
        """
        将 config.ini 中的按键名解析为 (Qt.Key, pygame.K) 元组。
        优先查覆盖表，否则通过反射从 Qt/pygame 动态获取。
        """
        if not name:
            return None

        # 1) 覆盖表优先
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

        # 2) 动态反射：Qt.Key.Key_<name>
        try:
            qt_key = getattr(Qt.Key, f"Key_{name}")
        except AttributeError:
            return None

        # 3) 动态反射：pygame.K_<name>（先小写，再大写）
        try:
            pg_key = getattr(pygame, f"K_{name.lower()}")
        except AttributeError:
            try:
                pg_key = getattr(pygame, f"K_{name.upper()}")
            except AttributeError:
                return None

        return (qt_key, pg_key)
