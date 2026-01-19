# -*- coding: utf-8 -*-
"""Scheduler 包

调度器核心功能模块化组织：

核心模块:
- core.py: 核心调度器类
- lifecycle.py: 生命周期管理
- task_dispatcher.py: 任务调度
- state_manager.py: 状态管理
- plan_file_manager.py: Plan文件管理
- validation.py: 输入验证
- ui_bridge.py: UI桥接
- utils.py: 工具函数
- scheduling_service.py: 定时调度服务

子系统:
- execution/: 执行管理（ExecutionManager, ExecutionService, DispatchService）
- queues/: 队列管理（TaskQueue, InterruptService）
"""

from .core import Scheduler

# 导出子系统（可选，按需导入）
# from .execution import ExecutionManager, ExecutionService, DispatchService
# from .queues import TaskQueue, InterruptService

__all__ = ['Scheduler']
