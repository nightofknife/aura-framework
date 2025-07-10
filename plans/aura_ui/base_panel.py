# plans/aura_ui/base_panel.py (全新文件)
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any


class BasePanel(ttk.Frame):
    """
    所有IDE面板的基类。
    提供了统一的初始化、生命周期管理和对核心服务的访问。
    """

    def __init__(self, parent: ttk.Frame, scheduler: Any, ide: Any, **kwargs: Any):
        """
        统一的构造函数。
        :param parent: 父Tkinter组件。
        :param scheduler: 核心调度器实例。
        :param ide: AuraIDE主应用实例，用于跨面板通信。
        :param kwargs: 其他可选的依赖，如'log_queue'。
        """
        super().__init__(parent)
        self.parent = parent
        self.scheduler = scheduler
        self.ide = ide

        # 从kwargs中获取可选依赖
        self.log_queue = kwargs.get('log_queue')

        # 用于存储通过 schedule_update 注册的 after 调用ID
        self._after_ids: Dict[str, str] = {}

        # 模板方法模式：子类应该在这里创建它们的UI组件
        self._create_widgets()

        # 子类可以在这里加载初始数据
        self._initial_load()

    def _create_widgets(self):
        """
        【抽象方法】子类必须实现此方法来创建其UI组件。
        """
        raise NotImplementedError("子类必须实现 _create_widgets 方法")

    def _initial_load(self):
        """
        【可选钩子】子类可以实现此方法来执行初始数据加载。
        默认情况下什么都不做。
        """
        pass

    def schedule_update(self, delay_ms: int, callback_func: callable, name: str):
        """
        一个安全的 after 方法，会自动记录ID以便在销毁时取消。
        :param delay_ms: 延迟的毫秒数。
        :param callback_func: 要调用的函数。
        :param name: 此调度任务的唯一名称，用于取消。
        """
        # 如果已存在同名任务，先取消它
        if name in self._after_ids:
            self.after_cancel(self._after_ids[name])

        # 安排新的任务并存储ID
        after_id = self.after(delay_ms, callback_func)
        self._after_ids[name] = after_id

    def destroy(self):
        """
        【核心】重写destroy方法以确保所有挂起的after调用都被取消。
        """
        print(f"Destroying {self.__class__.__name__} and cancelling scheduled updates...")
        # 取消所有通过 schedule_update 注册的 after 调用
        for name, after_id in self._after_ids.items():
            print(f"  - Cancelling scheduled update: {name}")
            self.after_cancel(after_id)

        # 调用父类的 destroy 方法来销毁UI组件
        super().destroy()

