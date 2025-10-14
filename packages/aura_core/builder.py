# -*- coding: utf-8 -*-
"""负责从插件源码构建 API 定义文件的构建器。

此模块的核心功能是 `build_package_from_source`，它会遍历一个插件包的
所有 Python 文件和 `tasks` 目录，通过静态分析和动态加载的方式，
抽取出所有公开的 Service、Action 和 Task 入口点的信息，
并最终将这些信息序列化成一个 `api.yaml` 文件。

这个 `api.yaml` 文件是 Aura 框架实现“无源码分发”和“延迟加载”的关键。
框架在运行时可以仅读取这个 API 文件来了解一个插件提供了哪些能力，
而无需加载其全部 Python 模块。
"""

import importlib.util
import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Set, Optional, Any, Dict, List

import yaml

from packages.aura_core.api import ACTION_REGISTRY, ActionDefinition
from packages.aura_core.api import service_registry, ServiceDefinition
from packages.aura_core.plugin_definition import PluginDefinition
from packages.aura_core.logger import logger

_PROCESSED_MODULES: Set[str] = set()
PROJECT_BASE_PATH: Optional[Path] = None
API_FILE_NAME = "api.yaml"


def set_project_base_path(base_path: Path):
    """设置项目的根路径，用于计算模块的相对路径。

    Args:
        base_path: 项目的根目录 `Path` 对象。
    """
    global PROJECT_BASE_PATH
    PROJECT_BASE_PATH = base_path


def build_package_from_source(plugin_def: PluginDefinition):
    """从插件的源代码构建其 `api.yaml` 文件。

    此函数是构建流程的主入口。它会：
    1. 清理构建缓存。
    2. 遍历插件目录下的所有 `.py` 文件，加载并处理其中的 Service 和 Action 定义。
    3. 扫描 `tasks` 目录下的 `.yaml` 文件，查找被标记为入口点的任务。
    4. 将收集到的所有公开 API 信息整合成一个字典。
    5. 将该字典以 YAML 格式写入到插件根目录下的 `api.yaml` 文件中。

    Args:
        plugin_def: 要构建的插件的 `PluginDefinition` 对象。
    """
    logger.debug(f"从源码构建包: {plugin_def.canonical_id}")
    clear_build_cache()
    package_path = plugin_def.path
    public_services = []
    public_actions = []
    for file_path in sorted(package_path.rglob("*.py")):
        if file_path.name.startswith('__'): continue
        module_name = _get_module_name_from_path(file_path)
        if module_name in _PROCESSED_MODULES: continue
        try:
            module = _load_module_from_path(file_path, module_name)
            if module:
                services_info = _process_service_file(module, plugin_def)
                actions_info = _process_action_file(module, plugin_def)
                if services_info: public_services.extend(services_info)
                if actions_info: public_actions.extend(actions_info)
        except Exception as e:
            relative_file_path = file_path.relative_to(PROJECT_BASE_PATH)
            logger.error(f"处理文件 '{relative_file_path}' 时失败: {e}", exc_info=True)
    tasks_dir = package_path / 'tasks'
    public_tasks = []
    if tasks_dir.is_dir():
        public_tasks = _process_task_entry_points(tasks_dir, plugin_def)
    api_data = {
        "aura_version": "3.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_identity": plugin_def.canonical_id,
        "exports": {"services": public_services, "actions": public_actions},
        "entry_points": {"tasks": public_tasks}
    }
    api_file_path = package_path / API_FILE_NAME
    try:
        with open(api_file_path, 'w', encoding='utf-8') as f:
            yaml.dump(api_data, f, allow_unicode=True, sort_keys=False, indent=2)
        logger.info(f"已为包 '{plugin_def.canonical_id}' 生成 API 文件: {api_file_path.name}")
    except Exception as e:
        logger.error(f"写入 API 文件 '{api_file_path}' 失败: {e}")


def clear_build_cache():
    """清除已处理模块的缓存。"""
    _PROCESSED_MODULES.clear()


def _process_service_file(module: Any, plugin_def: PluginDefinition) -> List[Dict]:
    """(私有) 从单个 Python 模块中提取并注册 Service 定义。

    Args:
        module: 已加载的 Python 模块对象。
        plugin_def: 当前正在处理的插件定义。

    Returns:
        一个列表，包含在该模块中找到的所有公开 Service 的信息字典。
    """
    public_services_info = []
    _PROCESSED_MODULES.add(module.__name__)
    for _, class_obj in inspect.getmembers(module, inspect.isclass):
        if class_obj.__module__ != module.__name__: continue
        if hasattr(class_obj, '_aura_service_meta'):
            meta = class_obj._aura_service_meta
            alias = meta['alias']
            fqid = f"{plugin_def.canonical_id}/{alias}"
            if service_registry.is_registered(fqid): continue
            definition = ServiceDefinition(alias=alias, fqid=fqid, service_class=class_obj, plugin=plugin_def,
                                           public=meta['public'])
            service_registry.register(definition)
            if definition.public:
                public_services_info.append({
                    "alias": definition.alias,
                    "class_name": definition.service_class.__name__,
                    "source_file": str(Path(inspect.getfile(definition.service_class)).relative_to(plugin_def.path))
                })
    return public_services_info


def _process_action_file(module: Any, plugin_def: PluginDefinition) -> List[Dict]:
    """(私有) 从单个 Python 模块中提取并注册 Action 定义。

    Args:
        module: 已加载的 Python 模块对象。
        plugin_def: 当前正在处理的插件定义。

    Returns:
        一个列表，包含在该模块中找到的所有公开 Action 的信息字典。
    """
    public_actions_info = []
    _PROCESSED_MODULES.add(module.__name__)
    for _, func_obj in inspect.getmembers(module, inspect.isfunction):
        if func_obj.__module__ != module.__name__: continue
        if hasattr(func_obj, '_aura_action_meta'):
            meta = func_obj._aura_action_meta
            definition = ActionDefinition(func=func_obj, name=meta['name'], read_only=meta['read_only'],
                                          public=meta['public'], service_deps=meta.get('services', {}),
                                          plugin=plugin_def)
            ACTION_REGISTRY.register(definition)
            if definition.public:
                public_actions_info.append({
                    "name": definition.name, "function_name": definition.func.__name__,
                    "source_file": str(Path(inspect.getfile(definition.func)).relative_to(plugin_def.path)),
                    "required_services": definition.service_deps
                })
    return public_actions_info


def _process_task_entry_points(tasks_dir: Path, plugin_def: PluginDefinition) -> List[Dict]:
    """(私有) 扫描 tasks 目录，查找并返回所有公开的任务入口点信息。

    此函数会遍历 `tasks` 目录下的所有 `.yaml` 文件，并解析其内容，
    寻找 `meta.entry_point: true` 标记来识别公开任务。
    它同时支持单文件单任务（旧格式）和单文件多任务（新格式）的 YAML 结构。

    Args:
        tasks_dir: 指向插件 `tasks` 目录的 Path 对象。
        plugin_def: 当前正在处理的插件定义。

    Returns:
        一个列表，包含找到的所有公开任务入口点的信息字典。
    """
    public_tasks_info = []
    for task_path in tasks_dir.rglob("*.yaml"):
        try:
            with open(task_path, 'r', encoding='utf-8') as f:
                all_task_data = yaml.safe_load(f)
            if not isinstance(all_task_data, dict):
                continue

            def process_single_task(task_id_in_plan: str, task_def: dict):
                """辅助函数，处理单个任务定义"""
                if isinstance(task_def, dict) and 'meta' in task_def:
                    meta = task_def['meta']
                    if meta.get('entry_point') is True:
                        task_info = {
                            "title": meta.get("title", task_id_in_plan),
                            "description": meta.get("description", ""),
                            "task_id": task_id_in_plan,
                            "icon": meta.get("icon")
                        }
                        public_tasks_info.append(task_info)
                        logger.debug(f"发现公开任务入口点: {task_info['title']} in {plugin_def.canonical_id}")

            if 'steps' in all_task_data:
                task_name_from_file = task_path.relative_to(tasks_dir).with_suffix('').as_posix()
                process_single_task(task_name_from_file, all_task_data)
            else:
                for task_key, task_definition in all_task_data.items():
                    process_single_task(task_key, task_definition)

        except Exception as e:
            logger.warning(f"解析任务文件元数据失败 '{task_path.relative_to(plugin_def.path)}': {e}")

    return public_tasks_info


def _get_module_name_from_path(file_path: Path) -> str:
    """(私有) 根据文件路径计算出其对应的 Python 模块名。

    Args:
        file_path: Python 文件的 Path 对象。

    Returns:
        对应的模块名字符串 (例如, "packages.my_plugin.services.my_service")。

    Raises:
        RuntimeError: 如果项目的根路径 `PROJECT_BASE_PATH` 尚未设置。
    """
    if PROJECT_BASE_PATH is None: raise RuntimeError("Builder的PROJECT_BASE_PATH未被初始化。")
    try:
        relative_path = file_path.relative_to(PROJECT_BASE_PATH)
    except ValueError:
        relative_path = Path(file_path.name)
    return str(relative_path).replace('/', '.').replace('\\', '.').removesuffix('.py')


def _load_module_from_path(file_path: Path, module_name: str) -> Optional[Any]:
    """(私有) 从给定的文件路径动态加载一个 Python 模块。

    为了避免重复加载，此函数会先检查 `sys.modules`。

    Args:
        file_path: 要加载的 `.py` 文件的路径。
        module_name: 要赋给该模块的名称。

    Returns:
        加载成功的模块对象，如果失败则返回 None 或抛出异常。
    """
    if module_name in sys.modules:
        logger.debug(f"模块 '{module_name}' 已在 sys.modules 中，直接返回。")
        return sys.modules[module_name]
    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None: logger.warning(f"无法为文件创建模块规范: {file_path}"); return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        logger.debug(f"已加载模块: {module_name}")
        return module
    except Exception:
        logger.error(f"从路径 '{file_path}' 加载模块时发生未知错误。", exc_info=True)
        if module_name in sys.modules: del sys.modules[module_name]
        raise
