# -*- coding: utf-8 -*-
"""配置管理系统。

核心组件:
- get_config_value: 配置加载函数
- ConfigManager: 配置管理器
- validate_task_definition: Schema验证器
- TemplateRenderer: 模板渲染器
"""

from .loader import get_config_value
from .manager import ConfigManager
from .validator import validate_task_definition
from .template import TemplateRenderer

__all__ = [
    'get_config_value',
    'ConfigManager',
    'validate_task_definition',
    'TemplateRenderer',
]
