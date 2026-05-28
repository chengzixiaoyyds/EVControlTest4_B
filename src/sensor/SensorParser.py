"""
传感器数据解析模块 —— 解析上行数据帧，实现过流检测与统计。

上行帧格式（15 字节，小端序）：
  Byte  0~ 1: 帧头  0xFA 0xAF
  Byte  2   : 帧类型 uint8（0x53 = ASCII 'S'，代表传感器数据）
  Byte  3~ 6: 温度 float LE（°C）
  Byte  7   : 进水检测 uint8（0=正常，非0=告警）
  Byte  8~11: 电流 float LE（A）
  Byte 12   : 异或校验 uint8（对字节2~11逐字节异或）
  Byte 13~14: 帧尾  0xFB 0xBF
"""

import struct
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
    """
    上行传感器数据帧字段解析器。

    使用方式：由 SerialComm 通过 CommandBuffer 提取完整帧后，
    将 15 字节原始帧传入 parse() 提取各字段。
    """

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
    过流保护监控器。
    - 根据电流阈值判断当前是否过流
    - 累计总过流时间（秒）
    - 支持回调通知
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
        return self._is_overcurrent

    @property
    def total_overcurrent_time(self) -> float:
        """累计总过流时间（秒），含当前正在进行的过流"""
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
        每次收到新的电流数据时调用。

        :param current:   当前电流值（A）
        :param timestamp: 时间戳（秒），默认使用 time.time()
        """
        if timestamp is None:
            timestamp = time.time()

        now_over = current > self._threshold

        if now_over and not self._is_overcurrent:
            # 进入过流
            self._is_overcurrent = True
            self._overcurrent_start = timestamp
            if self._on_enter_overcurrent:
                self._on_enter_overcurrent(current)

        elif not now_over and self._is_overcurrent:
            # 退出过流：累计本次过流时长
            if self._overcurrent_start is not None:
                duration = timestamp - self._overcurrent_start
                self._total_overcurrent_time += duration
            else:
                duration = 0.0
            self._is_overcurrent = False
            self._overcurrent_start = None
            if self._on_exit_overcurrent:
                self._on_exit_overcurrent(current, duration)

        self._last_update_time = timestamp

    def reset_statistics(self) -> None:
        """重置过流累计时间统计"""
        self._total_overcurrent_time = 0.0
        self._overcurrent_start = None
        self._is_overcurrent = False
        self._last_update_time = None

    def get_status_dict(self) -> dict:
        """返回当前过流状态摘要（供 GUI 使用）"""
        return {
            "is_overcurrent": self._is_overcurrent,
            "threshold": self._threshold,
            "total_overcurrent_time": self.total_overcurrent_time,
        }
