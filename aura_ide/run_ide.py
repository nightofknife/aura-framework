# aura_ide/run_ide.py (修改版)

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from aura_ide.main_window import MainWindow
from aura_ide.widgets.texture_generator import TextureManager

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 1. 在启动时生成一次性的随机纹理
    texture_manager = TextureManager()

    # 2. 加载原始的QSS文件 (不再需要替换)
    try:
        qss_path = Path(__file__).parent.parent / "aura_ide/resources/styles/style.qss"
        print(qss_path)
        with open(qss_path, "r",encoding='utf-8') as f:
            app.setStyleSheet(f.read())
            print(f"Style loaded from {qss_path}")
    except FileNotFoundError:
        print(f"Warning: Stylesheet not found at {qss_path}. Using default style.")

    # 【修改】将texture_manager实例传递给MainWindow
    window = MainWindow(texture_manager)
    window.show()

    sys.exit(app.exec())
