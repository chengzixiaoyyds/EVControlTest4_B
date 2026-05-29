"""
程序入口 —— 组装 AppCore + MainWindow，启动 Qt 事件循环。

启动流程:
  1. 创建 QApplication
  2. AppCore(cfg_path) 加载全部配置
  3. MainWindow(keyboard_cfg) 构建界面
  4. 绑定回调: AppCore ←→ MainWindow
  5. QTimer 驱动 125Hz 控制循环 + 50Hz UI 刷新

职责边界: 只做组装，不读取配置、不处理业务逻辑。
"""
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

# ── 主函数 ──
def main():
    # ── Qt 应用 ──
    app = QApplication(sys.argv)
    app.setApplicationName("ROV Control Station")

    # ── 后端核心（AppCore 统一加载所有配置）──
    cfg_path = os.path.join(_BASE_DIR, "config", "config.ini")
    core = AppCore(cfg_path)
    window = MainWindow(core.keyboard_config)

    # ── 回调绑定 ──
    callbacks = AppCallbacks()
    window.set_callbacks_ref(callbacks)
    core.set_callbacks(callbacks)

    # ── 启动后端（所有参数从 config.ini 读取） ──
    connected = core.start()
    print(f"[Main] 串口连接: {'成功' if connected else '失败'}")

    # ── 按钮事件（直接绑定 AppCore 方法，不在此处理业务逻辑）──
    window.bind_snapshot(core.snapshot)

    def on_record_toggle(checked: bool):
        if checked:
            if not core.start_recording():
                window.set_record_button_checked(False)
        else:
            core.stop_recording()

    window.bind_record_toggle(on_record_toggle)
    window.bind_reset_overcurrent(core.reset_overcurrent_statistics)
    window.bind_stopwatch_toggle(core.toggle_stopwatch)
    window.bind_stopwatch_reset(core.reset_stopwatch)

    # ── 主循环定时器（频率由 AppCore 从 config.ini 统一读取）──
    loop_timer = QTimer()
    freq = core.control_frequency
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
