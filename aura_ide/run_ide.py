# run_ide.py

import sys
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

    # 在这里可以设置全局样式表
    # with open("path/to/style.qss", "r") as f:
    #     app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
