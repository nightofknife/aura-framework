# main.py (最终修正版)

import sys
from pathlib import Path
import tkinter as tk

# 确保项目根目录在Python的搜索路径中，这对于 'packages.' 导入至关重要
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from packages.aura_ui.main_window import AuraIDE
from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.scheduler import Scheduler


def main():
    """程序主入口"""
    scheduler = None
    try:
        # 步骤 1: 首先创建核心调度器实例
        # 所有的服务和行为加载都在这一步完成。如果这里失败，UI就不会启动。
        logger.info("正在初始化Aura核心调度器...")
        scheduler = Scheduler()
        logger.info("核心调度器初始化完毕。")

        # 步骤 2: 然后创建UI，并将已完全初始化的 scheduler 注入
        logger.info("正在启动Aura IDE界面...")
        root = tk.Tk()
        # 将 scheduler 实例传递给 AuraIDE 的构造函数
        app = AuraIDE(root, scheduler)
        logger.info("Aura IDE 启动成功。")
        root.mainloop()

    except Exception as e:
        # 捕获所有启动过程中的严重错误
        log_message = f"Aura IDE 启动失败: {e}"
        logger.error(log_message)

        # 尝试弹出一个简单的错误对话框
        try:
            import tkinter.messagebox as messagebox
            temp_root = tk.Tk()
            temp_root.withdraw()
            messagebox.showerror("严重错误", f"应用程序启动失败:\n\n{e}")
            temp_root.destroy()
        except Exception as msg_e:
            print(f"无法显示错误对话框: {msg_e}")


if __name__ == "__main__":
    main()
