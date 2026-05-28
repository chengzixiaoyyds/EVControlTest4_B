"""
.ui → .py 编译 —— 调用 pyside6-uic + 自动修复枚举兼容。

用法:  python ui/compile_ui.py

PySide6 6.10+ 废弃了 Qt.AlignCenter 等旧枚举，
本脚本在编译后自动替换为新式命名。
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_SRC = ROOT / "ui" / "main_window.ui"
UI_OUT = ROOT / "src" / "gui" / "Ui_MainWindow.py"

# 1. 用 pyside6-uic 编译
result = subprocess.run(
    ["pyside6-uic", str(UI_SRC), "-o", str(UI_OUT)],
    capture_output=True, text=True,
)
if result.returncode != 0:
    print(f"[ERROR] pyside6-uic 失败:\n{result.stderr}")
    exit(1)

# 2. 读取生成文件
text = UI_OUT.read_text(encoding="utf-8")

# 3. 替换旧式枚举 → 新式枚举（PySide6 6.10+）
replacements = [
    ("Qt.AlignCenter",              "Qt.AlignmentFlag.AlignCenter"),
    ("Qt.AlignRight|Qt.AlignVCenter", "Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter"),
    ("Qt.AlignLeft",                 "Qt.AlignmentFlag.AlignLeft"),
    ("Qt.AlignTop",                  "Qt.AlignmentFlag.AlignTop"),
    ("Qt.AlignBottom",              "Qt.AlignmentFlag.AlignBottom"),
    ("Qt.AlignHCenter",             "Qt.AlignmentFlag.AlignHCenter"),
]
for old, new in replacements:
    text = text.replace(old, new)

# 4. 写回
UI_OUT.write_text(text, encoding="utf-8")
print(f"[OK] {UI_SRC.name} → {UI_OUT}")
