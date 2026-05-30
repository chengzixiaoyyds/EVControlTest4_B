"""
传感器解析 —— 上行帧字段提取 + 过流监控。

上行帧 15B (0x53 'S'): 温度 / 进水检测 / 电流

拆分为两个独立类:
  SensorParser     — 纯函数，帧 → 结构化数据
  OvercurrentMonitor — 状态机，累计过流时长 + 回调通知
"""

import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


# ════════════════════════════════════════════════════════
#  数据结构
# ════════════════════════════════════════════════════════

@dataclass
class SensorData:
    """单帧传感器数据"""
    frame_type: int = 0x53           # 帧类型（0x53='S'）
    temperature: float = 0.0         # 温度 (°C)
    water_ingress: bool = False      # 进水告警（True=进水）
    current: float = 0.0             # 电流 (A)
    raw_frame: Optional[bytes] = None  # 原始帧（调试用）
    timestamp: float = field(default_factory=time.time)


# ════════════════════════════════════════════════════════
#  帧字段解析器（帧提取与校验由 CommandBuffer 负责）
# ════════════════════════════════════════════════════════

class SensorParser:
    """上行帧解析 —— 纯静态方法，输入 bytes 输出 SensorData"""

    @staticmethod
    def parse(frame: bytes) -> SensorData:
        """
        从一条已校验的 15 字节上行帧中提取传感器字段。

        :param frame: CommandBuffer.get_command() 返回的完整帧
        :return:      SensorData 实例
        """
        frame_type = frame[2]
        temperature = struct.unpack('<f', frame[3:7])[0]
        water_ingress_raw = frame[7]
        current = struct.unpack('<f', frame[8:12])[0]

        return SensorData(
            frame_type=frame_type,
            temperature=temperature,
            water_ingress=(water_ingress_raw != 0),
            current=current,
            raw_frame=frame,
        )


# ════════════════════════════════════════════════════════
#  过流检测与统计
# ════════════════════════════════════════════════════════

class OvercurrentMonitor:
    """
    过流状态机 —— 检测电流越限，累计过流时长。

    两个状态: 正常 ↔ 过流
    进入/退出时触发回调通知 GUI。
    """

    def __init__(self, threshold: float = 10.0):
        """
        :param threshold: 过流阈值（A），超过即视为过流
        """
        self._threshold = threshold
        self._is_overcurrent = False
        self._total_overcurrent_time = 0.0  # 累计总过流时间（秒）
        self._overcurrent_start: Optional[float] = None  # 本次过流开始时刻
        self._last_update_time: Optional[float] = None

        # 回调
        self._on_enter_overcurrent: Optional[Callable[[float], None]] = None
        self._on_exit_overcurrent: Optional[Callable[[float, float], None]] = None

        # 线程安全锁（可重入，避免 get_status_dict → total_overcurrent_time 自死锁）
        self._lock = threading.RLock()

    # ── 属性 ──
    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._threshold = value

    @property
    def is_overcurrent(self) -> bool:
        """当前是否处于过流状态"""
        with self._lock:
            return self._is_overcurrent

    @property
    def total_overcurrent_time(self) -> float:
        """累计总过流时间（秒），含当前正在进行的过流"""
        with self._lock:
            total = self._total_overcurrent_time
            if self._is_overcurrent and self._overcurrent_start is not None:
                total += time.time() - self._overcurrent_start
            return total

    # ── 回调设置 ──
    def set_callbacks(
        self,
        on_enter: Optional[Callable[[float], None]] = None,
        on_exit: Optional[Callable[[float, float], None]] = None,
    ) -> None:
        """
        设置过流状态变化的回调。
        :param on_enter: 进入过流时调用 on_enter(current_amps)
        :param on_exit:  退出过流时调用 on_exit(current_amps, duration)
        """
        self._on_enter_overcurrent = on_enter
        self._on_exit_overcurrent = on_exit

    # ── 核心更新 ──
    def update(self, current: float, timestamp: Optional[float] = None) -> None:
        """
        根据当前电流值更新过流状态与累计时间。
        每次收到新的电流数据时调用。线程安全。

        :param current:   当前电流值（A）
        :param timestamp: 时间戳（秒），默认使用 time.time()
        """
        if timestamp is None:
            timestamp = time.time()

        # 锁内仅更新状态，捕获待触发的回调，锁外执行以避免持锁期间调用外部代码
        enter_cb = None
        enter_current = 0.0
        exit_cb = None
        exit_current = 0.0
        exit_duration = 0.0

        with self._lock:
            now_over = current > self._threshold

            if now_over and not self._is_overcurrent:
                # 进入过流
                self._is_overcurrent = True
                self._overcurrent_start = timestamp
                enter_cb = self._on_enter_overcurrent
                enter_current = current

            elif not now_over and self._is_overcurrent:
                # 退出过流：累计本次过流时长
                if self._overcurrent_start is not None:
                    duration = timestamp - self._overcurrent_start
                    self._total_overcurrent_time += duration
                else:
                    duration = 0.0
                self._is_overcurrent = False
                self._overcurrent_start = None
                exit_cb = self._on_exit_overcurrent
                exit_current = current
                exit_duration = duration

            self._last_update_time = timestamp

        # 锁外调用回调，避免持锁期间执行外部代码导致潜在死锁
        if enter_cb:
            enter_cb(enter_current)
        if exit_cb:
            exit_cb(exit_current, exit_duration)

    def reset_statistics(self) -> None:
        """重置过流累计时间统计（线程安全）"""
        exit_cb = None
        exit_current = 0.0
        exit_duration = 0.0
        with self._lock:
            was_overcurrent = self._is_overcurrent
            if was_overcurrent:
                if self._overcurrent_start is not None:
                    exit_duration = time.time() - self._overcurrent_start
                    self._total_overcurrent_time += exit_duration
                    exit_cb = self._on_exit_overcurrent
                    exit_current = 0.0  # 当前电流未知，传 0.0 表示空/无读数
                else:
                    # 防御：状态不一致（过流中但缺少开始时间），强制修复
                    self._is_overcurrent = False
            self._overcurrent_start = None
            self._is_overcurrent = False
            self._last_update_time = None
        # 锁外调用退出回调，通知 UI 过流已结束
        if exit_cb:
            exit_cb(exit_current, exit_duration)

    def get_status_dict(self) -> dict:
        """返回当前过流状态摘要（供 GUI 使用，线程安全）"""
        with self._lock:
            return {
                "is_overcurrent": self._is_overcurrent,
                "threshold": self._threshold,
                "total_overcurrent_time": self.total_overcurrent_time,
            }
