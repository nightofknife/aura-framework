# aura_ide/run_ide.py

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

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
