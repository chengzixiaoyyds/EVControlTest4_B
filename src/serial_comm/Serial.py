"""
串口通信模块 —— 封装串口连接、后台接收与帧收发。

依赖:
  - pyserial
  - CommandBuffer（循环缓冲区，解析上行帧）

═══════════════════════════════════════════════════
  上行帧（下位机 → 上位机，15 字节，由 CommandBuffer 解析）
═══════════════════════════════════════════════════
  Byte  0~ 1: 帧头  0xFA 0xAF
  Byte  2   : 帧类型 uint8（0x53 = ASCII 'S'）
  Byte  3~ 6: 温度 float LE（°C）
  Byte  7   : 进水检测 uint8（0=正常，非0=告警）
  Byte  8~11: 电流 float LE（A）
  Byte 12   : 异或校验 uint8（对字节2~11异或）
  Byte 13~14: 帧尾  0xFB 0xBF

═══════════════════════════════════════════════════
  下行请求帧（上位机 → 下位机，5 字节）
═══════════════════════════════════════════════════
  Byte  0~ 1: 帧头  0xFA 0xAF
  Byte  2   : 帧类型 uint8（0x52 = ASCII 'R'）
  Byte  3~ 4: 帧尾  0xFB 0xBF

═══════════════════════════════════════════════════
  下行数据帧（上位机 → 下位机，23 字节，小端序）
═══════════════════════════════════════════════════
  Byte  0~ 1: 帧头  0xFA 0xAF
  Byte  2   : 帧类型 uint8（0x49 = ASCII 'I'）
  Byte  3~ 6: Y 推力  float LE（N）
  Byte  7~10: X 推力  float LE（N，预留）
  Byte 11~14: Z 推力  float LE（N）
  Byte 15~18: Yaw 扭矩 float LE（N·m）
  Byte 19   : 机械臂角度 uint8（0x00~0xFF）
  Byte 20   : 异或校验 uint8（对字节2~19异或）
  Byte 21~22: 帧尾  0xFB 0xBF
"""

import struct
import threading
import time
from typing import Callable, Optional

import serial

from .CommandBuffer import CommandBuffer

# ---------- 帧常量 ----------
_HEADER = bytes([0xFA, 0xAF])
_TAIL = bytes([0xFB, 0xBF])


class SerialComm:
    """串口通信管理类"""

    def __init__(
        self,
        port: str,
        baudrate: int,
        timeout: float,
        poll_interval: float,
    ):
        """
        :param port:          串口号，如 'COM8'
        :param baudrate:      波特率
        :param timeout:       串口读超时（秒）
        :param poll_interval: 接收线程轮询间隔（秒）
        """
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._poll_interval = poll_interval

        self._ser: Optional[serial.Serial] = None
        self._buffer = CommandBuffer()
        self._stop_event = threading.Event()
        self._recv_thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[bytes], None]] = None

        self._lock = threading.Lock()

    # ---------- 连接管理 ----------
    def connect(self) -> bool:
        """打开串口并启动接收线程，成功返回 True"""
        try:
            self._ser = serial.Serial(
                self._port, self._baudrate, timeout=self._timeout
            )
        except serial.SerialException as e:
            print(f"[SerialComm] 无法打开串口 {self._port}: {e}")
            return False

        self._stop_event.clear()
        self._recv_thread = threading.Thread(
            target=self._receiver, daemon=True
        )
        self._recv_thread.start()
        print(f"[SerialComm] 已连接 {self._port} @ {self._baudrate}")
        return True

    def disconnect(self) -> None:
        """关闭串口，停止接收线程"""
        self._stop_event.set()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=2.0)
            self._recv_thread = None
        if self._ser is not None and self._ser.is_open:
            self._ser.close()
        self._ser = None
        print("[SerialComm] 串口已关闭")

    def is_connected(self) -> bool:
        """串口是否已打开"""
        return self._ser is not None and self._ser.is_open

    # ---------- 回调 ----------
    def set_callback(self, callback: Optional[Callable[[bytes], None]]) -> None:
        """设置接收到完整帧时的回调函数，参数为 15 字节原始帧"""
        self._callback = callback

    # ---------- 发送 ----------
    @staticmethod
    def build_request_frame() -> bytes:
        """构建下行请求帧（5 字节），帧类型 0x52('R')"""
        return _HEADER + bytes([0x52]) + _TAIL

    @staticmethod
    def build_data_frame(
        thrust_y: float,
        thrust_x: float,
        thrust_z: float,
        yaw_torque: float,
        arm_angle: int,
    ) -> bytes:
        """
        构建下行数据帧（23 字节），帧类型 0x49('I')。
        :param thrust_y:   Y 方向推力（N）
        :param thrust_x:   X 方向推力（N，预留）
        :param thrust_z:   Z 方向推力（N）
        :param yaw_torque: Yaw 扭矩（N·m）
        :param arm_angle:  机械臂角度（0~255）
        :return:           23 字节帧
        """
        payload = struct.pack(
            '<BffffB', 0x49, thrust_y, thrust_x, thrust_z, yaw_torque, arm_angle
        )
        xor_val = 0
        for b in payload:
            xor_val ^= b
        return _HEADER + payload + bytes([xor_val]) + _TAIL

    def send_frame(self, frame: bytes) -> bool:
        """发送一帧数据，成功返回 True"""
        ser = self._ser
        if ser is None or not ser.is_open:
            print("[SerialComm] 串口未连接，无法发送")
            return False
        with self._lock:
            ser.write(frame)
        return True

    # ---------- 接收线程 ----------
    def _receiver(self) -> None:
        """后台线程：持续读串口 → 写缓冲区 → 提取帧 → 回调"""
        while not self._stop_event.is_set():
            try:
                ser = self._ser
                if ser is None or not ser.is_open:
                    break
                with self._lock:
                    waiting = ser.in_waiting
                    if waiting:
                        data = ser.read(waiting)
                    else:
                        data = b''
                if data:
                    self._buffer.write(data)
                    while True:
                        frame = self._buffer.get_command()
                        if frame is None:
                            break
                        if self._callback:
                            self._callback(frame)
            except serial.SerialException:
                break
            except Exception:
                break
            time.sleep(self._poll_interval)
