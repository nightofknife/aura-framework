# packages/aura_core/builder.py (多任务格式支持版)
"""
负责从插件源码构建静态 API 定义文件（api.yaml）。

此模块的核心功能是扫描插件目录中的 Python 源代码（用于服务和行为）和
YAML 文件（用于任务），通过静态分析和动态导入的方式，提取出所有公开的
API 定义。然后，它将这些信息序列化成一个名为 `api.yaml` 的文件，
存放在插件的根目录下。

这个 `api.yaml` 文件作为插件的“清单”，使得 Aura 框架可以在不实际加载
插件代码的情况下，预先了解其提供的所有能力（服务、行为、任务入口点）。
这对于实现插件的懒加载、依赖解析和高效启动至关重要。
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
"""一个内部集合，用于跟踪已处理过的模块，防止重复加载。"""

PROJECT_BASE_PATH: Optional[Path] = None
"""项目的根目录路径，用于将文件绝对路径转换为模块名。"""

API_FILE_NAME = "api.yaml"
"""生成的 API 定义文件的标准名称。"""


def set_project_base_path(base_path: Path):
    """
    设置构建器使用的项目根路径。

    这个路径是计算模块导入名称所必需的。必须在调用任何构建函数之前设置。

    Args:
        base_path (Path): 项目的绝对根路径。
    """
    global PROJECT_BASE_PATH
    PROJECT_BASE_PATH = base_path


def build_package_from_source(plugin_def: PluginDefinition):
    """
    从插件的源代码构建其 `api.yaml` 文件。

    这是构建过程的主函数。它会：
    1. 清理构建缓存。
    2. 遍历插件目录下的所有 `.py` 文件。
    3. 加载每个文件作为 Python 模块。
    4. 从模块中提取由 `@register_service` 和 `@register_action` 装饰的定义。
    5. 扫描 `tasks` 子目录，查找并解析作为入口点的任务。
    6. 将所有收集到的公开 API 信息写入插件根目录下的 `api.yaml` 文件。

    Args:
        plugin_def (PluginDefinition): 需要构建的插件的定义对象。
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
    """
    清空已处理模块的缓存。

    在每次执行新的构建任务前调用，以确保所有模块都被重新检查。
    """
    _PROCESSED_MODULES.clear()


def _process_service_file(module: Any, plugin_def: PluginDefinition) -> List[Dict]:
    """在单个模块中扫描并注册服务定义。"""
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
    """在单个模块中扫描并注册行为定义。"""
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
    """
    扫描 tasks 目录，查找并返回公开的任务入口点信息。

    此函数支持两种任务文件格式：
    1.  旧格式：一个 YAML 文件只包含一个任务。
    2.  新格式：一个 YAML 文件可以包含多个命名的任务。

    它通过检查任务定义中的 `meta.entry_point: true` 标志来识别公开任务。
    """
    public_tasks_info = []
    for task_path in tasks_dir.rglob("*.yaml"):
        try:
            with open(task_path, 'r', encoding='utf-8') as f:
                all_task_data = yaml.safe_load(f)
            if not isinstance(all_task_data, dict):
                continue

            def process_single_task(task_id_in_plan: str, task_def: dict):
                """辅助函数，处理单个任务定义。"""
                if isinstance(task_def, dict) and 'meta' in task_def:
                    meta = task_def['meta']
                    if meta.get('entry_point') is True:
                        task_info = {
                            "title": meta.get("title", task_id_in_plan),
                            "description": meta.get("description", ""),
                            "task_id": task_id_in_plan,  # 使用任务ID而不是文件名
                            "icon": meta.get("icon")
                        }
                        public_tasks_info.append(task_info)
                        logger.debug(f"发现公开任务入口点: {task_info['title']} in {plugin_def.canonical_id}")

            # 判断格式并处理
            if 'steps' in all_task_data:  # 旧格式: 单文件单任务
                task_name_from_file = task_path.relative_to(tasks_dir).with_suffix('').as_posix()
                process_single_task(task_name_from_file, all_task_data)
            else:  # 新格式: 单文件多任务
                for task_key, task_definition in all_task_data.items():
                    process_single_task(task_key, task_definition)

        except Exception as e:
            logger.warning(f"解析任务文件元数据失败 '{task_path.relative_to(plugin_def.path)}': {e}")

    return public_tasks_info


def _get_module_name_from_path(file_path: Path) -> str:
    """根据文件路径和已设置的根路径计算出 Python 模块名。"""
    if PROJECT_BASE_PATH is None: raise RuntimeError("Builder的PROJECT_BASE_PATH未被初始化。")
    try:
        relative_path = file_path.relative_to(PROJECT_BASE_PATH)
    except ValueError:
        relative_path = Path(file_path.name)
    return str(relative_path).replace('/', '.').replace('\\', '.').removesuffix('.py')


def _load_module_from_path(file_path: Path, module_name: str) -> Optional[Any]:
    """从给定的文件路径动态加载一个 Python 模块。"""
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
