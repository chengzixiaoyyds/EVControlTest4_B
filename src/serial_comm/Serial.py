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
    """串口通信管理类 —— 支持断线自动重连"""

    def __init__(
        self,
        port: str,
        baudrate: int,
        timeout: float,
        poll_interval: float,
        reconnect_interval: float = 2.0,
    ):
        """
        :param port:              串口号，如 'COM8'
        :param baudrate:          波特率
        :param timeout:           串口读超时（秒）
        :param poll_interval:     接收线程轮询间隔（秒）
        :param reconnect_interval: 断线后重连间隔（秒）
        """
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._reconnect_interval = reconnect_interval

        self._ser: Optional[serial.Serial] = None
        self._buffer = CommandBuffer()
        self._stop_event = threading.Event()
        self._recv_thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[bytes], None]] = None
        self._status_callback: Optional[Callable[[bool], None]] = None

        self._lock = threading.Lock()
        self._connected = False
        self._write_fail_count = 0          # 连续写失败计数
        self._WRITE_FAIL_THRESHOLD = 5      # 连续失败阈值（超过则判定端口死亡）

    # ---------- 连接管理 ----------
    def connect(self) -> bool:
        """打开串口并启动后台连接管理器（含自动重连），返回当前是否已连通"""
        self._stop_event.clear()
        # 立即尝试一次连接（同步，在调用线程中完成）
        if self._try_open_port():
            self._set_connected(True)
            print(f"[SerialComm] 已连接 {self._port} @ {self._baudrate}")
        else:
            # 初始连接失败，显式通知上层（_connected 初始即为 False，_set_connected 不会触发回调）
            if self._status_callback:
                self._status_callback(False)
        # 无论成功与否，启动后台连接管理器（负责接收和断线重连）
        self._recv_thread = threading.Thread(
            target=self._connection_manager, daemon=True
        )
        self._recv_thread.start()
        return self._connected

    def disconnect(self) -> None:
        """关闭串口，停止接收/重连线程"""
        self._stop_event.set()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=2.0)
            self._recv_thread = None
        self._close_port()
        self._set_connected(False)
        print("[SerialComm] 串口已关闭")

    def is_connected(self) -> bool:
        """串口是否已打开"""
        return self._connected and self._ser is not None and self._ser.is_open

    # ---------- 状态回调 ----------
    def set_status_callback(self, callback: Optional[Callable[[bool], None]]) -> None:
        """设置连接状态变化回调，参数为 bool（True=已连接）"""
        self._status_callback = callback

    def _set_connected(self, state: bool) -> None:
        """更新内部连接状态并触发回调"""
        prev = self._connected
        self._connected = state
        if state != prev and self._status_callback:
            self._status_callback(state)

    # ---------- 底层端口操作 ----------
    def _try_open_port(self) -> bool:
        """尝试打开串口，成功返回 True（线程安全）"""
        try:
            new_ser = serial.Serial(
                self._port, self._baudrate, timeout=self._timeout,
                write_timeout=0.1,
            )
        except serial.SerialException as e:
            print(f"[SerialComm] 无法打开串口 {self._port}: {e}")
            return False
        # 持锁替换 _ser，避免与 send_frame() / _close_port() 竞态
        with self._lock:
            self._ser = new_ser
        return True

    def _close_port(self) -> None:
        """安全关闭串口（线程安全）"""
        with self._lock:
            if self._ser is not None:
                try:
                    if self._ser.is_open:
                        self._ser.close()
                except Exception:
                    pass
                self._ser = None

    # ---------- 连接管理线程（接收 + 断线重连） ----------
    def _connection_manager(self) -> None:
        """
        后台线程：首次立即尝试连接，之后持续接收数据；断线后自动重连。
        """
        need_wait = False  # 首次不等待，直接尝试连接
        while not self._stop_event.is_set():
            # ── 未连接：尝试连接或重连 ──
            if self._ser is None or not self._ser.is_open:
                self._set_connected(False)
                if need_wait:
                    print(f"[SerialComm] 串口断开，{self._reconnect_interval}s 后重试...")
                    if self._stop_event.wait(self._reconnect_interval):
                        break
                need_wait = True

                if self._try_open_port():
                    self._buffer = CommandBuffer()  # 清空残留数据
                    self._set_connected(True)
                    print(f"[SerialComm] 已连接 {self._port} @ {self._baudrate}")
                else:
                    continue  # 打开失败，回到循环顶部等待/重试

            # ── 接收数据 ──
            try:
                with self._lock:
                    ser = self._ser
                    if ser is None or not ser.is_open:
                        continue
                    # in_waiting 和 read(waiting) 均在锁内执行，
                    # 消除 TOCTOU：避免锁外使用时端口被 _close_port() 并发关闭。
                    # read 读取已知可用字节数，不会阻塞，锁持有时间极短。
                    waiting = ser.in_waiting
                    if waiting:
                        data = ser.read(waiting)
                    else:
                        data = b''
                if data:
                    written = self._buffer.write(data)
                    if written == 0:
                        print("[SerialComm] 警告: 缓冲区写入失败，数据丢失")
                    while True:
                        frame = self._buffer.get_command()
                        if frame is None:
                            break
                        if self._callback:
                            self._callback(frame)
            except (serial.SerialException, OSError):
                print("[SerialComm] 串口读异常，进入重连流程")
                self._close_port()
                continue
            except Exception:
                self._close_port()
                continue

            time.sleep(self._poll_interval)

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
        """发送一帧数据，成功返回 True（线程安全，write 在锁内防止多线程数据交错）

        连续超时策略：单次 SerialTimeoutException 可能是 USB 总线瞬时抖动，
        仅计数不关闭端口；连续失败达到阈值才判定端口死亡并触发重连。
        SerialException（句柄失效等硬故障）则立即关闭端口。
        """
        should_close = False
        with self._lock:
            ser = self._ser
            if ser is None or not ser.is_open:
                return False
            try:
                ser.write(frame)
                #print(f"\r[SerialComm] 发送帧: {frame.hex()}", end='')
                self._write_fail_count = 0  # 成功写，清零连续失败计数
                return True
            except serial.SerialTimeoutException:
                # 瞬时间歇，计数。达到阈值才判定端口死亡
                self._write_fail_count += 1
                if self._write_fail_count >= self._WRITE_FAIL_THRESHOLD:
                    print(f"[SerialComm] 连续 {self._write_fail_count} 次写超时，判定端口死亡")
                    # 先在锁内置 None，阻止接收线程继续读写本端口
                    self._ser = None
                    self._write_fail_count = 0
                    should_close = True
                else:
                    return False
            except serial.SerialException:
                # 硬故障（句柄失效等），先在锁内置 None，阻止接收线程继续读写
                self._ser = None
                self._write_fail_count = 0
                should_close = True
        # ── 锁外安全关闭已分离的端口对象 ──
        if should_close:
            try:
                if ser.is_open:
                    ser.close()
            except Exception:
                pass
        return False
