"""
循环缓冲区模块 —— 按固定帧格式从字节流中提取完整数据帧。

帧格式（固定 15 字节，小端序）：
  Byte  0~ 1: 帧头  0xFA 0xAF
  Byte  2   : 帧类型 uint8（如 0x53 = ASCII 'S'）
  Byte  3~ 6: 温度 float（小端序，单位°C）
  Byte  7   : 进水检测 uint8（0=正常，非0=告警）
  Byte  8~11: 电流 float（小端序，单位A）
  Byte 12   : 异或校验 uint8（对字节2~11逐字节异或）
  Byte 13~14: 帧尾  0xFB 0xBF
"""

_FRAME_LEN = 15

_IDX_XOR = 12


class CommandBuffer:
    """循环缓冲区，从串口字节流中解析完整数据帧"""

    BUFFER_SIZE = 256

    def __init__(self):
        self.buffer = bytearray(self.BUFFER_SIZE)
        self.read_index = 0
        self.write_index = 0

    # ---------- 指针操作 ----------
    def _read(self, index: int) -> int:
        """读取缓冲区第 index 位（自动循环）"""
        return self.buffer[index % self.BUFFER_SIZE]

    def _add_read_index(self, length: int) -> None:
        """读指针前进 length 字节"""
        self.read_index = (self.read_index + length) % self.BUFFER_SIZE

    def get_length(self) -> int:
        """未处理数据长度"""
        return (self.write_index - self.read_index + self.BUFFER_SIZE) % self.BUFFER_SIZE

    def get_remain(self) -> int:
        """缓冲区剩余空间"""
        return self.BUFFER_SIZE - self.get_length()

    def write(self, data: bytes) -> int:
        """写入数据，返回实际写入的字节数（空间不足返回0）"""
        length = len(data)
        if self.get_remain() < length:
            return 0

        first_part = self.BUFFER_SIZE - self.write_index
        if length <= first_part:
            self.buffer[self.write_index : self.write_index + length] = data
            self.write_index += length
        else:
            self.buffer[self.write_index :] = data[:first_part]
            second_part = length - first_part
            self.buffer[:second_part] = data[first_part:]
            self.write_index = second_part
        return length

    # ---------- 帧提取 ----------
    def get_command(self) -> bytes | None:
        """
        从缓冲区提取一条完整帧，返回 15 字节的 bytes；
        数据不足、帧头/帧尾不匹配或异或校验失败时跳过并继续搜索。
        """
        while True:
            if self.get_length() < _FRAME_LEN:
                return None

            # 校验帧头 (0xFA 0xAF)
            if (self._read(self.read_index) != 0xFA
                    or self._read(self.read_index + 1) != 0xAF):
                self._add_read_index(1)
                continue

            # 校验帧尾 (0xFB 0xBF)
            if (self._read(self.read_index + 13) != 0xFB
                    or self._read(self.read_index + 14) != 0xBF):
                self._add_read_index(1)
                continue

            # 计算异或校验（对字节 2~11 逐字节异或）
            xor_val = 0
            for i in range(2, _IDX_XOR):
                xor_val ^= self._read(self.read_index + i)
            if xor_val != self._read(self.read_index + _IDX_XOR):
                self._add_read_index(1)
                continue

            # 提取完整帧
            frame = bytes(self._read(self.read_index + i) for i in range(_FRAME_LEN))
            self._add_read_index(_FRAME_LEN)
            return frame