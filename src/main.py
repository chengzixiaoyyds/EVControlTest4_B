"""
ROV 控制站 —— 程序入口

用法:
    python src/main.py

所有参数在 config/config.ini 中配置。
"""
import configparser
import os
import sys
import time

# 确保 src 上级目录在 sys.path 中
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from src.AppCore import AppCore, AppCallbacks
from src.gui import MainWindow
from src.camera import Camera
from src.joystick import ControlState
from src.utils import Stopwatch

# ── 媒体输出目录 ──
def _ensure_output_dir(key: str, default: str) -> str:
    """从 config.ini 读取输出路径，确保目录存在"""
    cfg = configparser.ConfigParser()
    cfg_path = os.path.join(_BASE_DIR, "config", "config.ini")
    d = default
    if os.path.exists(cfg_path):
        cfg.read(cfg_path, encoding="utf-8")
        try:
            d = cfg.get("media", key, fallback=default)
        except Exception:
            pass
    if not os.path.isabs(d):
        d = os.path.join(_BASE_DIR, d)
    os.makedirs(d, exist_ok=True)
    return d


# ── 主函数 ──
def main():
    # ── Qt 应用 ──
    app = QApplication(sys.argv)
    app.setApplicationName("ROV Control Station")

    # ── 后端核心 ──
    core = AppCore()
    window = MainWindow()

    # ── 回调绑定 ──
    callbacks = AppCallbacks()
    window.set_callbacks_ref(callbacks)
    core.set_callbacks(callbacks)

    # ── 启动后端（所有参数从 config.ini 读取） ──
    connected = core.start()
    print(f"[Main] 串口连接: {'成功' if connected else '失败'}")

    # ── 按钮事件 ──
    snapshot_counter = 0

    screenshot_dir = _ensure_output_dir("screenshot_dir", "screenshots")
    record_dir = _ensure_output_dir("record_dir", "recordings")

    def on_snapshot():
        nonlocal snapshot_counter
        snapshot_counter += 1
        path = os.path.join(screenshot_dir, f"screenshot_{snapshot_counter:04d}.png")
        ok = core.snapshot(path)
        print(f"[Main] 截图 → {path} ({'OK' if ok else 'FAIL'})")

    def on_record_toggle(checked: bool):
        if checked:
            path = os.path.join(record_dir, f"record_{time.strftime('%Y%m%d_%H%M%S')}.avi")
            if not core.start_recording(path):
                window.btnRecord.setChecked(False)
        else:
            core.stop_recording()

    def on_reset_overcurrent():
        core.reset_overcurrent_statistics()
        print("[Main] 过流统计已重置")

    window.bind_snapshot(on_snapshot)
    window.bind_record_toggle(on_record_toggle)
    window.bind_reset_overcurrent(on_reset_overcurrent)

    # 秒表
    def on_stopwatch_toggle():
        sw = core.stopwatch
        if sw.is_running:
            sw.pause()
        else:
            sw.resume() if sw.elapsed > 0 else sw.start()

    def on_stopwatch_reset():
        core.stopwatch.reset()

    window.bind_stopwatch_toggle(on_stopwatch_toggle)
    window.bind_stopwatch_reset(on_stopwatch_reset)

    # 快捷键回调 → JoystickController 统一管理
    jc = core.get_joystick_controller()
    if jc:
        jc.on_snapshot = on_snapshot
        jc.on_record_toggle = lambda: on_record_toggle(not core.is_recording)

    # ── 主循环定时器（频率从 config.ini 读取） ──
    loop_timer = QTimer()
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(_BASE_DIR, "config", "config.ini"), encoding="utf-8")
    freq = cfg.getfloat("control", "frequency", fallback=125.0) if cfg.has_section("control") else 125.0
    loop_timer.setInterval(int(1000.0 / freq))
    fps_update_time = time.time()
    fps_frame_count = 0

    def on_loop_tick():
        nonlocal fps_update_time, fps_frame_count

        # 手柄/键盘 → 串口下发（统一由 JoystickController 处理）
        cs = core.update()

        # 发送控制状态给 UI
        if cs is not None:
            window.sig_control_update.emit(cs)

        # 视频帧
        frame_rgb = core.get_frame_rgb()
        if frame_rgb is not None:
            window.update_video_frame(frame_rgb)

        # 过流累计时间
        window.update_overcurrent_time(core.overcurrent_status["total_overcurrent_time"])

        # 录像状态
        window.update_record_status(core.is_recording, core.record_duration)

        # 秒表
        sw = core.stopwatch
        window.update_stopwatch_display(sw.elapsed, sw.is_running)

        # FPS 统计
        fps_frame_count += 1
        now = time.time()
        if now - fps_update_time >= 1.0:
            fps = fps_frame_count / (now - fps_update_time)
            window.update_fps(fps)
            fps_frame_count = 0
            fps_update_time = now

    loop_timer.timeout.connect(on_loop_tick)
    loop_timer.start()

    # ── UI 定时器（50 Hz 刷新显示） ──
    window.start_ui_timer()

    # ── 显示窗口 ──
    window.show()

    # ── 事件循环 ──
    try:
        exit_code = app.exec()
    finally:
        print("[Main] 正在关闭...")
        loop_timer.stop()
        core.stop()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
