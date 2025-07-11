# plans/aura_ui/services/launcher_service.py (优化版)

import tkinter as tk
from typing import Optional

from packages.aura_core.api import register_service
from packages.aura_core.scheduler import Scheduler
from ..main_window import AuraIDE


@register_service(alias="ui_launcher", public=True)
class UILauncherService:
    """
    负责启动和管理Aura IDE图形界面的服务。
    遵循标准服务生命周期 (start, stop)。
    """

    def __init__(self):
        # 【修改】使用更明确的类型提示
        self.root: Optional[tk.Tk] = None
        self.ide_instance: Optional[AuraIDE] = None

    def start(self):
        """
        【新增】标准服务启动方法。
        在服务管理器启动时被调用，此处我们只做日志记录，
        因为UI的启动是阻塞的，应该由主程序显式调用 launch()。
        """
        print("UI Launcher Service started.")
        # 在这里可以进行一些非UI的预加载或配置

    def stop(self):
        """
        【新增】标准服务停止方法。
        在服务管理器停止时被调用，用于安全地关闭UI。
        """
        print("UI Launcher Service stopping...")
        if self.root and self.root.winfo_exists():
            # 【修改】通过调用 destroy() 来触发UI的关闭流程
            self.root.destroy()
        self.root = None
        self.ide_instance = None
        print("UI Launcher Service stopped.")

    def launch(self, scheduler_instance: Scheduler):
        """
        启动Aura IDE。
        这个方法会创建一个阻塞的UI主循环，应该在主线程中调用。

        :param scheduler_instance: 核心调度器实例。
        """
        if self.is_running():
            print("UI已经在运行中。")
            self.root.lift()  # 将窗口置于顶层
            return

        try:
            self._create_ui(scheduler_instance)
            # 这是一个阻塞调用，会启动UI事件循环
            # 当窗口被关闭（例如点击关闭按钮或调用 self.root.destroy()）时，mainloop会退出
            self.root.mainloop()
        finally:
            # 【新增】确保在UI循环结束后清理资源
            print("UI mainloop has finished.")
            self.root = None
            self.ide_instance = None

    def _create_ui(self, scheduler_instance: Scheduler):
        """
        【新增】将UI的创建逻辑封装成一个私有方法。
        """
        self.root = tk.Tk()
        # 【新增】设置一个协议处理器，当用户点击窗口关闭按钮时，调用我们的stop方法
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        # 实例化IDE主窗口
        self.ide_instance = AuraIDE(self.root, scheduler_instance)

    def is_running(self) -> bool:
        """
        【新增】一个辅助方法，用于检查UI是否正在运行。
        """
        return bool(self.root and self.root.winfo_exists())
