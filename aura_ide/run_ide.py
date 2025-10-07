"""
Aura IDE 的主启动脚本。

该脚本负责：
1.  初始化 `QApplication`，这是任何 PySide6 应用程序所必需的。
2.  创建 `TextureManager` 实例，用于生成和管理UI的背景纹理。
3.  加载全局的 QSS 样式表，为整个应用程序定义外观。
4.  实例化并显示主窗口 `MainWindow`。
5.  启动应用程序的事件循环。

要运行 Aura IDE，请直接执行此脚本。
"""
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
