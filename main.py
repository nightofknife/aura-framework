# main.py (优化版)

import sys
import tkinter as tk
from pathlib import Path
from typing import Optional

# 确保项目根目录在Python的搜索路径中
# 这一步对于可执行文件打包（如PyInstaller）尤其重要
try:
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    base_path = Path(sys._MEIPASS)
except AttributeError:
    base_path = Path(__file__).resolve().parent

if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

from packages.aura_shared_utils.utils.logger import logger
from packages.aura_core.scheduler import Scheduler
from packages.aura_core.api import service_registry


class AuraApplication:
    """
    Aura IDE 应用程序的主封装类。
    负责初始化、运行和关闭核心组件。
    """
    def __init__(self):
        # 将核心组件作为实例属性，方便管理
        self.scheduler: Optional[Scheduler] = None

    def _initialize_scheduler(self):
        """初始化核心调度器，加载所有插件。"""
        logger.info("正在初始化Aura核心调度器...")
        self.scheduler = Scheduler()
        logger.info("核心调度器初始化完毕。")

    def _launch_ui(self):
        """通过服务注册中心查找并启动UI。"""
        if not self.scheduler:
            raise RuntimeError("调度器未初始化，无法启动UI。")

        logger.info("正在查找UI启动器服务...")
        try:
            # 从服务注册中心获取UI启动器服务实例
            ui_launcher = service_registry.get_service_instance("ui_launcher")
        except NameError:
            # 提供更明确的错误信息
            raise RuntimeError(
                "找不到 'ui_launcher' 服务。请确保 'aura.ui' 插件已正确安装并在 'pyproject.toml' 中声明。"
            )

        logger.info("UI启动器服务已找到，正在启动界面...")
        # 调用服务来启动UI，并将 scheduler 实例传递进去
        # 这个调用将会阻塞，直到UI窗口关闭
        ui_launcher.launch(self.scheduler)
        logger.info("Aura IDE 已关闭。")

    def _shutdown(self):
        """安全地停止所有服务和调度器。"""
        if self.scheduler and self.scheduler.is_scheduler_running.is_set():
            logger.info("正在停止调度器...")
            self.scheduler.stop_scheduler()
            logger.info("调度器已停止。程序退出。")

    def run(self):
        """应用程序的主运行循环。"""
        try:
            self._initialize_scheduler()
            self._launch_ui()
        except Exception as e:
            # 捕获所有启动过程中的严重错误
            log_message = f"Aura IDE 启动失败: {e}"
            logger.error(log_message, exc_info=True)
            self._show_error_dialog(e)
        finally:
            self._shutdown()

    @staticmethod
    def _show_error_dialog(error: Exception):
        """在启动失败时弹出一个简单的错误对话框。"""
        try:
            import tkinter.messagebox as messagebox
            temp_root = tk.Tk()
            temp_root.withdraw()  # 隐藏主窗口
            messagebox.showerror("严重错误", f"应用程序启动失败:\n\n{error}")
            temp_root.destroy()
        except Exception as msg_e:
            # 如果连Tkinter都无法工作，则在控制台打印错误
            print(f"无法显示Tkinter错误对话框: {msg_e}")


def main():
    """程序主入口点。"""
    app = AuraApplication()
    app.run()


if __name__ == "__main__":
    main()
