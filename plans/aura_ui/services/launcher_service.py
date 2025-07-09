# plans/aura_ui/services/launcher_service.py
import tkinter as tk
from packages.aura_core.api import register_service
from ..main_window import AuraIDE  # 从同级目录导入AuraIDE


@register_service(alias="ui_launcher", public=True)
class UILauncherService:
    """
    负责启动和管理Aura IDE图形界面的服务。
    """

    def __init__(self):
        self.root = None
        self.ide_instance = None

    def launch(self, scheduler_instance):
        """
        启动Aura IDE。
        这个方法会创建一个阻塞的UI主循环，应该在主线程中调用。

        :param scheduler_instance: 已经初始化并启动的Scheduler核心实例。
        """
        if self.root and self.root.winfo_exists():
            print("UI已经在运行中。")
            self.root.lift()
            return

        # 封装了原先在主程序入口的所有UI启动逻辑
        self.root = tk.Tk()
        self.ide_instance = AuraIDE(self.root, scheduler_instance)

        # 这是一个阻塞调用，会启动UI事件循环
        self.root.mainloop()
