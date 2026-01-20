# -*- coding: utf-8 -*-
"""Aura Core 类型系统

此包定义了框架中使用的核心值对象和类型。
"""

from .task_reference import TaskReference, parse_task_reference

__all__ = [
    'TaskReference',
    'parse_task_reference',
]
