import sys
from pathlib import Path
import tkinter as tk

# 确保项目根目录在Python的搜索路径中
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 【修改】不再直接导入UI类
# from plans.aura_ui.main_window import AuraIDE

from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.scheduler import Scheduler
# 【新增】从框架API导入服务注册中心
from packages.aura_core.api import service_registry


def main():
    """程序主入口"""
    scheduler = None
    try:
        # 步骤 1: 创建核心调度器实例
        # 这个过程会自动发现并加载所有插件，包括我们新的 aura.ui 插件，
        # 并将 UILauncherService 注册到系统中。
        logger.info("正在初始化Aura核心调度器...")
        scheduler = Scheduler()
        logger.info("核心调度器初始化完毕。")

        # 【修改】步骤 2: 不再直接创建UI，而是通过服务来启动
        logger.info("正在查找UI启动器服务...")

        # 从服务注册中心获取UI启动器服务
        try:
            ui_launcher = service_registry.get_service_instance("ui_launcher")
        except NameError:
            raise RuntimeError("找不到 'ui_launcher' 服务。请确保 'aura.ui' 插件已正确安装和加载。")

        logger.info("UI启动器服务已找到，正在启动界面...")

        # 调用服务来启动UI，并将 scheduler 实例传递进去
        # 这个调用将会阻塞，直到UI窗口关闭
        ui_launcher.launch(scheduler)

        logger.info("Aura IDE 已关闭。")

    except Exception as e:
        # 捕获所有启动过程中的严重错误
        log_message = f"Aura IDE 启动失败: {e}"
        logger.error(log_message, exc_info=True)  # 建议添加 exc_info=True 来记录完整的堆栈信息

        # 尝试弹出一个简单的错误对话框
        try:
            import tkinter.messagebox as messagebox
            temp_root = tk.Tk()
            temp_root.withdraw()
            messagebox.showerror("严重错误", f"应用程序启动失败:\n\n{e}")
            temp_root.destroy()
        except Exception as msg_e:
            print(f"无法显示错误对话框: {msg_e}")
    finally:
        # 【新增】添加一个 finally 块来确保调度器在程序退出前被停止
        if scheduler and scheduler.is_scheduler_running.is_set():
            logger.info("正在停止调度器...")
            scheduler.stop_scheduler()
            logger.info("调度器已停止。程序退出。")


if __name__ == "__main__":
    main()
