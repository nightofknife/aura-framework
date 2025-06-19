# src/core/action_loader.py

import importlib.util
from pathlib import Path
import sys
import inspect  # 【新增】
from typing import Set

from packages.aura_shared_utils.utils.logger import logger
# 【新增】导入我们需要的类
from packages.aura_shared_utils.models.plugin_definition import PluginDefinition
from packages.aura_system_actions.actions.decorators import ACTION_REGISTRY, ActionDefinition

_loaded_action_files: Set[Path] = set()


def load_actions_from_path(actions_path: Path, plugin_def: PluginDefinition):
    """
    【升级版】递归加载Action模块，并使用插件上下文完成最终注册。

    :param actions_path: 插件包内部的 'actions' 或 'notifier_actions' 目录路径。
    :param plugin_def: 【新增】当前正在加载的插件的定义对象。
    """
    if not actions_path.is_dir():
        return

    # 【修改】简化 glob 模式，使其更通用
    for file_path in actions_path.rglob("*.py"):
        if file_path in _loaded_action_files:
            continue
        if file_path.name.startswith('__'):
            continue

        try:
            # 你的模块名生成逻辑很好，我们保留它
            module_name = f"plugins.actions.{str(file_path).replace('/', '.').replace('\\', '.')}"
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None:
                logger.warning(f"无法为文件创建模块规范: {file_path}")
                continue

            module = importlib.util.module_from_spec(spec)

            # 你的 sys.path 处理逻辑也很好，我们保留它
            parent_dir = str(file_path.parent.resolve())
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)

            spec.loader.exec_module(module)

            if parent_dir in sys.path and parent_dir != '.':
                sys.path.remove(parent_dir)

            _loaded_action_files.add(file_path)
            logger.debug(f"成功加载Action模块: {file_path}")

            # --- 【核心新增逻辑】 ---
            # 模块加载后，查找所有被“标记”的函数
            for _, func in inspect.getmembers(module, inspect.isfunction):
                if hasattr(func, '_aura_action_meta'):
                    meta = func._aura_action_meta
                    # 创建包含完整信息的 ActionDefinition
                    action_def = ActionDefinition(
                        func=func,
                        name=meta['name'],
                        read_only=meta['read_only'],
                        service_deps=meta['services'],
                        plugin_def=plugin_def  # 注入关键的插件信息！
                    )
                    # 调用全局注册表进行注册
                    ACTION_REGISTRY.register(action_def)
            # ----------------------

        except Exception as e:
            logger.error(f"加载或注册Action模块 '{file_path.name}' 失败: {e}", exc_info=True)


def clear_loaded_actions():
    """【升级版】在重载时清空已加载文件的记录和注册表。"""
    _loaded_action_files.clear()
    ACTION_REGISTRY.clear()
