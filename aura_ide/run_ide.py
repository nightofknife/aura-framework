# run_ide.py (FINAL RECOMMENDED VERSION)

import sys
from pathlib import Path  # 1. 导入Path模块
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter

# 兼容旧版NodeGraphQt对QPainter的调用
try:
    if not hasattr(QPainter, "Antialiasing"):
        QPainter.Antialiasing = QPainter.RenderHint.Antialiasing
except Exception:
    pass

# 导入重构后的MainWindow
from aura_ide.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # --- 样式表加载 (更健壮的方式) ---
    # 2. 构建一个相对于当前文件位置的绝对路径
    #    Path(__file__) -> 当前文件的路径 (run_ide.py)
    #    .parent -> 获取其所在的目录
    #    / "resources/solarized_dark.qss" -> 拼接目标文件
    # qss_path = Path(__file__).parent / "resources/solarized_dark.qss"

    # try:
    #     with open(qss_path, "r", encoding="utf-8") as f:  # 建议加上 encoding
    #         app.setStyleSheet(f.read())
    # except FileNotFoundError:
    #     print(f"Stylesheet not found at: {qss_path}")
    # # --- 结束 ---

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
