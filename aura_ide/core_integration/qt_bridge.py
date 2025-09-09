# src/aura_ide/core_integration/qt_bridge.py

from __future__ import annotations
import asyncio
import queue
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtCore import QObject, Signal, QTimer

# 假设你这边有全局的 Scheduler 单例或通过 DI 注入
from packages.aura_core.scheduler import Scheduler


class QtBridge(QObject):
    core_status_changed = Signal(bool)
    ui_update_received = Signal(dict)
    raw_event_received = Signal(dict)
    runner_event_received = Signal(dict)  # 🆕 Runner 事件泵信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scheduler = Scheduler()  # 如果你的工程里是其它注入方式，请替换
        self._runner_event_timer: Optional[QTimer] = None
        self._ui_update_timer: Optional[QTimer] = None

        # 将 UI 更新队列连接到 Qt（Scheduler 会向 ui_update_queue 推送）
        q = queue.Queue(maxsize=200)
        self.scheduler.set_ui_update_queue(q)
        try:
            self.scheduler.trigger_full_ui_update()
        except Exception:
            pass
        # 周期性从 ui_update_queue 拉消息（非阻塞）
        self._ui_update_timer = QTimer(self)
        self._ui_update_timer.setInterval(80)
        self._ui_update_timer.timeout.connect(lambda: self._drain_ui_update_queue(q))
        self._ui_update_timer.start()

        # 事件总线镜像队列（Runner 用，手动 attach）
        self._runner_q: Optional[queue.Queue] = None

    # ---------- 调度器控制 ----------

    def start_core(self):
        self.scheduler.start_scheduler()
        self.core_status_changed.emit(True)

    def stop_core(self):
        self.scheduler.stop_scheduler()
        self.core_status_changed.emit(False)

    # ---------- Runner 事件泵 ----------

    def attach_runner_event_pump(self):
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
        q = self._runner_q
        if not q:
            return
        while True:
            try:
                ev = q.get_nowait()
                print(f"--- DEBUG: Event is being EMITTED from QtBridge: {ev.get('name')} ---")

            except queue.Empty:
                break
            except Exception:
                break
            if isinstance(ev, dict):
                # 原样给 Runner
                self.runner_event_received.emit(ev)
                # 是日志的话，也走一遍 raw_event_received（方便现有日志视图/处理链）
                if ev.get("name") == "log.emitted":
                    self.raw_event_received.emit(ev)

    def _drain_ui_update_queue(self, q: queue.Queue):
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break
            if isinstance(msg, dict):
                # 你可能有其它类型：master_status_update/run_status_single_update/full_status_update...
                self.ui_update_received.emit(msg)

    # ---------- 数据查询 ----------

    def list_plans(self) -> List[str]:
        try:
            return self.scheduler.get_all_plans()
        except Exception:
            return []

    def list_tasks(self, plan: str) -> List[str]:
        try:
            return self.scheduler.get_tasks_for_plan(plan)
        except Exception:
            return []

    def read_task_file(self, plan: str, relative_path: str) -> str:
        """
        读取 plans/<plan>/<relative_path> 文本（优先通过 Orchestrator 异步接口）。
        relative_path 例：'tasks/path/to/file.yaml'
        """
        try:
            loop = getattr(self.scheduler, "_loop", None)
            if loop:
                fut = asyncio.run_coroutine_threadsafe(
                    self.scheduler.get_file_content(plan, relative_path), loop
                )
                return fut.result(timeout=5)
            # 兜底：直接读磁盘
            p = Path(self.scheduler.base_path) / "plans" / plan / relative_path
            return p.read_text(encoding="utf-8")
        except Exception as e:
            raise

    # ---------- 运行控制 ----------

    def run_ad_hoc(self, plan: str, task_name: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            status = self.get_master_status()
            if not status.get("is_running"):
                # 自动拉起调度器，避免 ad-hoc 任务进入启动前缓冲区
                self.scheduler.start_scheduler()
            return self.scheduler.run_ad_hoc_task(plan, task_name, params or {})
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def stop_scheduler(self):
        self.scheduler.stop_scheduler()

    def start_scheduler(self):
        self.scheduler.start_scheduler()

    def get_master_status(self) -> dict:
        try:
            return self.scheduler.get_master_status()
        except Exception:
            return {"is_running": False}

    # ---------- 动作定义（供主窗口刷新工作区） ----------

    def get_all_action_definitions(self) -> list[dict]:
        """
        返回所有已注册的 Action 定义（透传 Scheduler.ACTION_REGISTRY）。
        兼容 main_window.on_core_status_changed() 的调用。
        """
        try:
            return self.scheduler.actions.get_all_action_definitions()
        except Exception:
            return []
