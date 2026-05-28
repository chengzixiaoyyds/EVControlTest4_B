"""
帧率限制器 —— 阻塞式频率控制 + 实际 FPS 统计。

不依赖 pygame，可用于任意循环。
"""

import time


class FrameRateLimiter:
    """频率控制器 —— wait() 阻塞至下一帧，自动统计实际 FPS"""

    def __init__(self, frequency: float):
        """
        :param frequency: 目标频率（Hz），如 125 表示每秒 125 次
        """
        self._interval = 1.0 / frequency if frequency > 0 else 0.0
        self._last_tick = time.perf_counter()
        self._frame_count = 0
        self._fps_update_time = self._last_tick
        self._actual_fps = 0.0

    @property
    def actual_fps(self) -> float:
        """实际运行帧率"""
        return self._actual_fps

    @property
    def interval(self) -> float:
        """帧间隔（秒）"""
        return self._interval

    def wait(self) -> float:
        """
        阻塞至下一帧，返回实际间隔（秒）。
        若已落后于目标频率则立即返回。
        """
        now = time.perf_counter()
        elapsed = now - self._last_tick
        sleep_time = self._interval - elapsed

        if sleep_time > 0:
            time.sleep(sleep_time)
            now = time.perf_counter()

        delta = now - self._last_tick
        self._last_tick = now

        # 每秒更新一次实际帧率
        self._frame_count += 1
        if now - self._fps_update_time >= 1.0:
            self._actual_fps = self._frame_count / (now - self._fps_update_time)
            self._frame_count = 0
            self._fps_update_time = now

        return delta

    def reset(self) -> None:
        """重置计时起点"""
        self._last_tick = time.perf_counter()
        self._frame_count = 0

    def should_process(self, target_fps: float) -> bool:
        """
        按指定频率节流，决定当前帧是否应该被处理。
        用于降低处理频率（如视频帧每隔N帧才做一次检测）。

        :param target_fps: 目标处理帧率
        :return: 当前帧是否应被处理
        """
        if target_fps <= 0 or self._interval <= 0:
            return True
        interval_frames = int(1.0 / (self._interval * target_fps) + 0.5)
        if interval_frames < 1:
            interval_frames = 1
        return self._frame_count % interval_frames == 0
