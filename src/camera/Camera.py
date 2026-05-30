"""
摄像头 —— 后台线程采集 + 非阻塞取帧，支持录像。

线程模型:
  主线程    → get_frame() / snapshot() / 录像启停
  采集线程  → 循环 read() + 录像写入 + FPS 统计

录像安全: _record_lock 保护启停与写入的并发。
依赖: OpenCV
"""

import threading
import time
from typing import Optional

import cv2
import numpy as np


class Camera:
    """
    USB 摄像头封装 —— 后台线程抓帧，主线程无阻塞获取。

    自动重连: 读取失败时释放并重新打开设备。
    录像: 采集线程中顺带写入 .avi，不额外开销。
    """

    def __init__(self, camera_id: int = 0, width: int = 640, height: int = 480, fps: int = 30):
        """
        :param camera_id: 摄像头设备 ID（默认 0）
        :param width:     采集分辨率宽度
        :param height:    采集分辨率高度
        :param fps:       期望帧率
        """
        self._camera_id = camera_id
        self._width = width
        self._height = height
        self._fps = fps

        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._cap_lock = threading.Lock()  # 保护 _cap 的赋值/释放，防止 stop() 与采集线程竞态
        self._running = threading.Event()  # 跨线程可见的停止标志（替代 bool，避免 GIL 依赖）
        self._thread: Optional[threading.Thread] = None
        self._connected = False

        # 帧统计
        self._frame_count = 0
        self._actual_fps = 0.0
        self._fps_update_time = time.time()

        # 录像
        self._video_writer: Optional[cv2.VideoWriter] = None
        self._recording = False
        self._record_lock = threading.Lock()  # 保护录像状态切换
        self._record_path: str = ""
        self._record_start_time: float = 0.0

    # ── 属性 ──
    @property
    def is_connected(self) -> bool:
        """摄像头是否已连接并正在采集"""
        return self._connected and self._running.is_set()

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def actual_fps(self) -> float:
        """实际采集帧率"""
        return self._actual_fps

    # ── 连接管理 ──
    def start(self) -> bool:
        """
        打开摄像头并启动采集线程。
        返回 True 表示成功。
        """
        if self._running.is_set():
            return True

        self._cap = cv2.VideoCapture(self._camera_id)
        if not self._cap.isOpened():
            print(f"[Camera] 无法打开摄像头 (id={self._camera_id})")
            self._cap = None
            return False

        # 设置分辨率与帧率
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

        # 读取一帧确认设置生效
        ret, frame = self._cap.read()
        if not ret or frame is None:
            print("[Camera] 摄像头打开但无法读取帧")
            self._cap.release()
            self._cap = None
            return False

        self._frame = frame
        self._connected = True
        self._running.set()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        actual_w = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print(f"[Camera] 已连接 (id={self._camera_id}, {actual_w:.0f}x{actual_h:.0f})")
        return True

    def stop(self) -> None:
        """停止采集并释放摄像头（含录像）"""
        self._running.clear()
        with self._record_lock:
            was_recording = self._recording
        if was_recording:
            self.stop_recording()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        with self._cap_lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None
        self._connected = False
        print("[Camera] 已停止")

    # ── 帧获取 ──
    def get_frame(self) -> Optional[np.ndarray]:
        """
        获取最新帧（非阻塞，线程安全）。
        返回 BGR 格式的 numpy 数组或 None。
        """
        with self._frame_lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def get_frame_rgb(self) -> Optional[np.ndarray]:
        """获取最新帧（RGB 格式），适用于 Qt 显示"""
        frame = self.get_frame()
        if frame is None:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # ── 后台采集线程（同时处理录像写入和 FPS 统计）──
    def _capture_loop(self) -> None:
        while self._running.is_set():
            with self._cap_lock:
                cap = self._cap
            if cap is None or not cap.isOpened():
                time.sleep(0.1)
                continue

            ret, frame = cap.read()
            if not ret or frame is None:
                # 尝试重连：加锁保护 _cap 的替换，防止 stop() 并发释放
                print("[Camera] 帧读取失败，尝试重连...")
                with self._cap_lock:
                    old_cap = self._cap
                    self._cap = None
                if old_cap is not None:
                    old_cap.release()
                with self._cap_lock:
                    self._cap = cv2.VideoCapture(self._camera_id)
                time.sleep(0.5)
                continue

            with self._frame_lock:
                self._frame = frame

            # 录像写入（加锁保护，防止主线程并发关闭录像）
            with self._record_lock:
                if self._recording and self._video_writer is not None:
                    try:
                        self._video_writer.write(frame)
                    except Exception:
                        pass

            # FPS 统计
            self._frame_count += 1
            now = time.time()
            elapsed = now - self._fps_update_time
            if elapsed >= 1.0:
                self._actual_fps = self._frame_count / elapsed
                self._frame_count = 0
                self._fps_update_time = now

    # ── 截图 ──
    def snapshot(self, filepath: str) -> bool:
        """
        保存当前帧为图片文件。
        :param filepath: 保存路径（如 'snapshot.png'）
        :return: 是否成功
        """
        frame = self.get_frame()
        if frame is None:
            return False
        return cv2.imwrite(filepath, frame)

    # ── 录像 ──
    @property
    def is_recording(self) -> bool:
        """是否正在录像"""
        with self._record_lock:
            return self._recording

    @property
    def record_duration(self) -> float:
        """当前录像已录制时长（秒）"""
        with self._record_lock:
            if not self._recording:
                return 0.0
            return time.time() - self._record_start_time

    def start_recording(self, filepath: str, codec: str = "XVID") -> bool:
        """
        开始录制视频（后台线程自动写入帧）。
        :param filepath: 保存路径（如 'record.avi'）
        :param codec:    编码格式 FourCC（默认 XVID）
        :return:         是否成功
        """
        with self._record_lock:
            if self._recording:
                print("[Camera] 已在录像中")
                return False

        fourcc = cv2.VideoWriter.fourcc(*codec)
        writer = cv2.VideoWriter(
            filepath, fourcc, self._fps, (self._width, self._height)
        )
        if not writer.isOpened():
            print(f"[Camera] 无法创建视频文件: {filepath}")
            writer.release()
            return False

        with self._record_lock:
            self._video_writer = writer
            self._recording = True
            self._record_path = filepath
            self._record_start_time = time.time()
        print(f"[Camera] 开始录像 → {filepath}")
        return True

    def stop_recording(self) -> str:
        """
        停止录像并返回文件路径。
        :return: 录制文件路径；若未在录像则返回空字符串
        """
        with self._record_lock:
            if not self._recording:
                return ""
            self._recording = False
            writer = self._video_writer
            self._video_writer = None
            # 锁内捕获时间戳与路径，避免锁外读取时被并发 start_recording() 覆写
            start_time = self._record_start_time
            record_path = self._record_path
            self._record_path = ""

        if writer is not None:
            writer.release()

        duration = time.time() - start_time
        print(f"[Camera] 录像已停止 ({duration:.1f}s) → {record_path}")
        return record_path

