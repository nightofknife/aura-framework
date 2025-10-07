"""
定义了 `QtBridge` 类，它是连接 Aura 核心后端和 PySide6 前端UI的关键桥梁。

该模块的核心是 `QtBridge`，一个 `QObject` 子类，它负责：
1.  **生命周期管理**: 封装对 `Scheduler` 的启动和停止调用。
2.  **数据通信**:
    - **从后端到UI**: 使用 `QTimer` 定期从后端的线程安全队列 (`queue.Queue`) 中
      拉取状态更新和事件，然后通过Qt的信号（Signals）将这些信息发射出去，
      供UI线程中的各个组件安全地接收和处理。
    - **从UI到后端**: 提供一系列同步方法，供UI组件调用。这些方法内部使用
      `asyncio.run_coroutine_threadsafe` 将请求安全地提交到后端 `asyncio`
      事件循环中执行，并阻塞等待返回结果。
3.  **API门面**: 为UI提供一个统一、简洁的API，用于查询后端数据（如方案列表、
    任务定义）和触发操作（如运行任务、读写文件），隐藏了复杂的跨线程和
    同步/异步通信细节。
"""
from __future__ import annotations
import asyncio
import queue
from pathlib import Path, PurePath
from typing import List, Dict, Any, Optional, Union

from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtWidgets import QStyle, QTreeWidgetItem

from packages.aura_core.scheduler import Scheduler


class QtBridge(QObject):
    """
    一个Qt对象，作为后端 Aura 核心与前端UI之间的桥梁。

    它使用信号和槽机制与UI线程通信，并管理对 `Scheduler` 的调用。
    """
    core_status_changed = Signal(bool)
    """当核心调度器启动或停止时发射，参数为 `True` (启动) 或 `False` (停止)。"""
    ui_update_received = Signal(dict)
    """当从后端接收到通用的UI更新消息时发射，参数为消息字典。"""
    raw_event_received = Signal(dict)
    """当接收到来自后端事件总线的原始事件时发射（主要用于日志）。"""
    runner_event_received = Signal(dict)
    """一个专用的信号，用于将事件泵送到 `RunnerPanel`。"""

    def __init__(self, parent: Optional[QObject] = None):
        """
        初始化Qt桥接器。

        Args:
            parent (Optional[QObject]): Qt父对象。
        """
        super().__init__(parent)
        self.scheduler = Scheduler()
        self._runner_event_timer: Optional[QTimer] = None
        self._ui_update_timer: Optional[QTimer] = None

        q: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=200)
        self.scheduler.set_ui_update_queue(q)
        try:
            self.scheduler.trigger_full_ui_update()
        except Exception:
            pass
        self._ui_update_timer = QTimer(self)
        self._ui_update_timer.setInterval(80)
        self._ui_update_timer.timeout.connect(lambda: self._drain_ui_update_queue(q))
        self._ui_update_timer.start()

        self._runner_q: Optional[queue.Queue[Dict[str, Any]]] = None

    # ---------- 调度器控制 ----------

    def start_core(self):
        """启动后端核心调度器。"""
        self.scheduler.start_scheduler()
        self.core_status_changed.emit(True)

    def stop_core(self):
        """停止后端核心调度器。"""
        self.scheduler.stop_scheduler()
        self.core_status_changed.emit(False)

    # ---------- Runner 事件泵 ----------

    def attach_runner_event_pump(self):
        """
        附加一个事件泵，专门用于将后端事件推送到 Runner 面板。
        这是一个独立的队列消费者，以确保 Runner 的高频事件不会
        影响其他UI更新。
        """
        if self._runner_event_timer and self._runner_event_timer.isActive():
            return
        try:
            self._runner_q = self.scheduler.get_ui_event_queue()
        except Exception:
            self._runner_q = None
            return
        self._runner_event_timer = QTimer(self)
        self._runner_event_timer.setInterval(50)
        self._runner_event_timer.timeout.connect(self._drain_runner_queue)
        self._runner_event_timer.start()

    def _drain_runner_queue(self):
        """从运行器事件队列中取出所有待处理事件并作为信号发射出去。"""
        q = self._runner_q
        if not q:
            return
        while True:
            try:
                ev = q.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break
            if isinstance(ev, dict):
                self.runner_event_received.emit(ev)
                if ev.get("name") == "log.emitted":
                    self.raw_event_received.emit(ev)

    def _drain_ui_update_queue(self, q: queue.Queue[Dict[str, Any]]):
        """从主UI更新队列中取出所有待处理消息并作为信号发射出去。"""
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break
            if isinstance(msg, dict):
                self.ui_update_received.emit(msg)

    # ---------- 数据查询 ----------

    def list_plans(self) -> List[str]:
        """
        获取所有已加载方案的名称列表。

        Returns:
            List[str]: 方案名称的列表。
        """
        try:
            return self.scheduler.get_all_plans()
        except Exception:
            return []

    def list_tasks(self, plan: str) -> List[str]:
        """
        获取指定方案下的所有任务名称列表。

        Args:
            plan (str): 方案的名称。

        Returns:
            List[str]: 该方案下的任务名称列表。
        """
        try:
            return self.scheduler.get_tasks_for_plan(plan)
        except Exception:
            return []

    def read_task_file(self, plan: str, relative_path: str) -> str:
        """
        读取方案目录内指定文件的文本内容。

        Args:
            plan (str): 方案名称。
            relative_path (str): 相对于方案根目录的文件路径。

        Returns:
            str: 文件的文本内容。
        """
        try:
            loop = getattr(self.scheduler, "_loop", None)
            if loop:
                fut = asyncio.run_coroutine_threadsafe(
                    self.scheduler.get_file_content(plan, relative_path), loop
                )
                return fut.result(timeout=5)
            p = Path(self.scheduler.base_path) / "plans" / plan / relative_path
            return p.read_text(encoding="utf-8")
        except Exception as e:
            raise

    # ---------- 运行控制 ----------

    def run_ad_hoc(self, plan: str, task_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        请求后端执行一个临时的（ad-hoc）任务。

        Args:
            plan (str): 任务所属的方案名称。
            task_name (str): 要执行的任务名称。
            params (Optional[Dict[str, Any]]): 传递给任务的输入参数。

        Returns:
            Dict[str, Any]: 一个包含操作状态和消息的字典。
        """
        try:
            status = self.get_master_status()
            if not status.get("is_running"):
                self.scheduler.start_scheduler()
            return self.scheduler.run_ad_hoc_task(plan, task_name, params or {})
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def stop_scheduler(self):
        """停止后端调度器。"""
        self.scheduler.stop_scheduler()

    def start_scheduler(self):
        """启动后端调度器。"""
        self.scheduler.start_scheduler()

    def get_master_status(self) -> Dict[str, bool]:
        """
        获取调度器的主要运行状态。

        Returns:
            Dict[str, bool]: 一个包含 `is_running` 键的字典。
        """
        try:
            return self.scheduler.get_master_status()
        except Exception:
            return {"is_running": False}

    # ---------- 动作定义（供主窗口刷新工作区） ----------

    def get_all_action_definitions(self) -> List[Dict[str, Any]]:
        """
        返回所有已注册的 Action 定义。

        Returns:
            List[Dict[str, Any]]: Action 定义的列表。
        """
        try:
            # 返回的是ActionDefinition对象列表，需要转换为字典
            return [a.__dict__ for a in self.scheduler.actions.get_all_action_definitions()]
        except Exception:
            return []

    def get_plan_files(self, plan_name: str) -> Dict[str, Any]:
        """
        获取指定方案包的文件目录树结构。

        Args:
            plan_name (str): 方案的名称。

        Returns:
            Dict[str, Any]: 一个表示文件和目录结构的嵌套字典。
        """
        try:
            return self.scheduler.get_plan_files(plan_name)
        except Exception as e:
            print(f"获取方案 '{plan_name}' 的文件时出错: {e}")
            return {}

    def read_file_bytes(self, plan: str, relative_path: str) -> bytes:
        """
        读取方案包内文件的二进制内容（例如，用于图片）。

        Args:
            plan (str): 方案名称。
            relative_path (str): 文件的相对路径。

        Returns:
            bytes: 文件的二进制内容。
        """
        try:
            loop = getattr(self.scheduler, "_loop", None)
            if loop and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    self.scheduler.get_file_content_bytes(plan, relative_path), loop
                )
                return fut.result(timeout=5)
            p = Path(self.scheduler.base_path) / "plans" / plan / relative_path
            return p.read_bytes()
        except Exception as e:
            raise

    def save_task_file(self, plan: str, relative_path: str, content: Union[str, bytes]):
        """
        将内容保存到方案包内的指定文件中。

        Args:
            plan (str): 方案名称。
            relative_path (str): 文件的相对路径。
            content (Union[str, bytes]): 要写入的文本或二进制内容。
        """
        print(f"DEBUG: QtBridge 收到保存请求: {plan}/{relative_path}")
        try:
            loop = getattr(self.scheduler, "_loop", None)
            if loop and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    self.scheduler.save_file_content(plan, relative_path, content), loop
                )
                fut.result(timeout=5)
            else:
                p = Path(self.scheduler.base_path) / "plans" / plan / relative_path
                p.parent.mkdir(parents=True, exist_ok=True)
                mode = 'wb' if isinstance(content, bytes) else 'w'
                encoding = None if isinstance(content, bytes) else 'utf-8'
                with open(p, mode, encoding=encoding) as f:
                    f.write(content)
        except Exception as e:
            raise

    def _populate_workspace_tree(self, parent_item: QTreeWidgetItem, dir_dict: Dict[str, Any]):
        """递归填充文件树视图的辅助函数。"""
        style = QApplication.style()
        dir_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        for name, content in sorted(dir_dict.items()):
            is_dir = isinstance(content, dict)
            child_item = QTreeWidgetItem([name])
            child_item.setIcon(0, dir_icon if is_dir else file_icon)

            parent_path_data = parent_item.data(0, Qt.ItemDataRole.UserRole)
            parent_path = ""
            if isinstance(parent_path_data, str):
                parent_path = parent_path_data

            relative_path = str(PurePath(parent_path) / name)
            child_item.setData(0, Qt.ItemDataRole.UserRole, relative_path)

            parent_item.addChild(child_item)
            if is_dir:
                self._populate_workspace_tree(child_item, content)


