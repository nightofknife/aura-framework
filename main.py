# main.py

import sys
from pathlib import Path
import tkinter as tk

# --- 【【【 这是解决问题的关键代码 】】】 ---
# 1. 获取项目根目录的绝对路径
#    Path(__file__).resolve() 获取当前文件 (main.py) 的绝对路径
#    .parent 获取其父目录，也就是项目的根目录
ROOT_DIR = Path(__file__).resolve().parent

# 2. 检查根目录是否已经在 sys.path 中
#    如果不在，就将其添加到 sys.path 的最前面
#    这确保了所有 "from packages.x.y import z" 形式的导入都能被正确解析
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
# --- 【【【 关键代码结束 】】】 ---


# 现在，所有的导入都将基于正确的根目录
from packages.aura_ui.main_window import AuraIDE
from packages.aura_shared_utils.utils.logger import logger

def main():
    """程序主入口"""
    try:
        root = tk.Tk()
        app = AuraIDE(root)
        logger.info("Aura IDE 启动成功。")
        root.mainloop()
    except Exception as e:
        # 在UI启动前的任何严重错误都应该被捕获和记录
        logger.critical(f"Aura IDE 启动失败: {e}", exc_info=True)
        # 如果有GUI，可以弹出一个错误对话框
        # import tkinter.messagebox as messagebox
        # messagebox.showerror("严重错误", f"应用程序启动失败:\n{e}")

if __name__ == "__main__":
    main()
