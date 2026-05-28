"""
秒表工具 —— 用于计时、统计等场景（进阶挑战）。

用法:
    sw = Stopwatch()
    sw.start()
    ... do something ...
    elapsed = sw.elapsed          # 已过秒数
    sw.pause()
    ... do something else ...
    sw.resume()
    total = sw.total              # 总运行秒数
"""

import time


class Stopwatch:
    """可暂停/恢复的秒表"""

    def __init__(self):
        self._start_time: float = 0.0
        self._accumulated: float = 0.0   # 累计运行时间（秒）
        self._running: bool = False

    # ── 控制 ──
    def start(self) -> None:
        """开始计时（若已运行则重置）"""
        self._start_time = time.perf_counter()
        self._accumulated = 0.0
        self._running = True

    def pause(self) -> None:
        """暂停计时"""
        if self._running:
            self._accumulated += time.perf_counter() - self._start_time
            self._running = False

    def resume(self) -> None:
        """恢复计时"""
        if not self._running:
            self._start_time = time.perf_counter()
            self._running = True

    def reset(self) -> None:
        """停止并清零"""
        self._start_time = 0.0
        self._accumulated = 0.0
        self._running = False

    # ── 只读属性 ──
    @property
    def elapsed(self) -> float:
        """自 start/resume 以来经过的秒数（含暂停前累计）"""
        if self._running:
            return self._accumulated + (time.perf_counter() - self._start_time)
        return self._accumulated

    @property
    def total(self) -> float:
        """别名，同 elapsed"""
        return self.elapsed

    @property
    def is_running(self) -> bool:
        return self._running

    # ── 格式化 ──
    def format(self, fmt: str = "mm:ss") -> str:
        """
        格式化显示时间。
        :param fmt: "mm:ss" 分:秒 或 "hh:mm:ss" 时:分:秒
        """
        seconds = int(self.elapsed)
        if fmt == "hh:mm:ss":
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            return f"{h:02d}:{m:02d}:{s:02d}"
        else:
            m = seconds // 60
            s = seconds % 60
            return f"{m:02d}:{s:02d}"

    def __str__(self) -> str:
        return self.format()
