# packages/aura_core/builder.py (最终完整修正版)

import importlib.util
import inspect
import sys
import yaml
from pathlib import Path
from typing import Set, Optional, Any, Dict, List
from datetime import datetime, timezone

from packages.aura_shared_utils.utils.logger import logger
from packages.aura_shared_utils.models.plugin_definition import PluginDefinition

from packages.aura_core.api import ACTION_REGISTRY, ActionDefinition
from packages.aura_core.api import service_registry, ServiceDefinition, hook_manager

_PROCESSED_MODULES: Set[str] = set()
PROJECT_BASE_PATH: Optional[Path] = None
API_FILE_NAME = "api.yaml"


def set_project_base_path(base_path: Path):
    global PROJECT_BASE_PATH
    PROJECT_BASE_PATH = base_path


def build_package_from_source(plugin_def: PluginDefinition):
    logger.debug(f"从源码构建包: {plugin_def.canonical_id}")
    clear_build_cache()

    package_path = plugin_def.path
    public_services = []
    public_actions = []
    public_tasks = []

    services_dir = package_path / 'services'
    if services_dir.is_dir():
        public_services = _build_from_directory(services_dir, plugin_def, _process_service_file)

    actions_dir = package_path / 'actions'
    if actions_dir.is_dir():
        public_actions = _build_from_directory(actions_dir, plugin_def, _process_action_file)

    tasks_dir = package_path / 'tasks'
    if tasks_dir.is_dir():
        # 【核心修正】调用现在已存在的函数
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
    _PROCESSED_MODULES.clear()


def _build_from_directory(directory: Path, plugin_def: PluginDefinition, processor_func) -> List[Dict]:
    public_apis = []
    for file_path in sorted(directory.rglob("*.py")):
        if file_path.name.startswith('__'):
            continue

        module_name = _get_module_name_from_path(file_path)
        if module_name in _PROCESSED_MODULES:
            logger.info(f"模块 '{module_name}' 已被间接处理，跳过。")
            continue

        try:
            # 【核心修正】将 try-except 块聚焦在真正可能出错的地方
            module = _load_module_from_path(file_path, module_name)
            if module:
                public_api_list = processor_func(module, plugin_def)
                if public_api_list:
                    public_apis.extend(public_api_list)
        except Exception as e:
            # 【核心修正】提供更简洁、集中的错误日志
            relative_file_path = file_path.relative_to(PROJECT_BASE_PATH)
            logger.error(f"处理文件 '{relative_file_path}' 时失败: {e}", exc_info=True)
            # 注意：我们不再在这里重新抛出异常，而是记录并继续处理下一个文件
            # 这使得一个插件的错误不会完全中断其他插件的构建过程
    return public_apis


def _process_service_file(module: Any, plugin_def: PluginDefinition) -> List[Dict]:
    public_services_info = []
    _PROCESSED_MODULES.add(module.__name__)

    for _, class_obj in inspect.getmembers(module, inspect.isclass):
        if class_obj.__module__ != module.__name__:
            continue

        if hasattr(class_obj, '_aura_service_meta'):
            meta = class_obj._aura_service_meta
            alias = meta['alias']
            fqid = f"{plugin_def.canonical_id}/{alias}"

            if service_registry.is_registered(fqid):
                continue

            definition = ServiceDefinition(
                alias=alias, fqid=fqid, service_class=class_obj,
                plugin=plugin_def, public=meta['public']
            )
            service_registry.register(definition)

            if definition.public:
                public_services_info.append({
                    "alias": definition.alias,
                    "class_name": definition.service_class.__name__,
                    "source_file": str(Path(inspect.getfile(definition.service_class)).relative_to(plugin_def.path))
                })
    return public_services_info


def _process_action_file(module: Any, plugin_def: PluginDefinition) -> List[Dict]:
    public_actions_info = []
    _PROCESSED_MODULES.add(module.__name__)

    for _, func_obj in inspect.getmembers(module, inspect.isfunction):
        if func_obj.__module__ != module.__name__:
            continue

        if hasattr(func_obj, '_aura_action_meta'):
            meta = func_obj._aura_action_meta
            definition = ActionDefinition(
                func=func_obj, name=meta['name'],
                read_only=meta['read_only'],
                public=meta['public'],
                service_deps=meta.get('services', {}),
                plugin=plugin_def
            )
            ACTION_REGISTRY.register(definition)

            if definition.public:
                public_actions_info.append({
                    "name": definition.name, "function_name": definition.func.__name__,
                    "source_file": str(Path(inspect.getfile(definition.func)).relative_to(plugin_def.path)),
                    "required_services": definition.service_deps
                })
    return public_actions_info


# 【【【核心修正：添加这个缺失的函数定义】】】
def _process_task_entry_points(tasks_dir: Path, plugin_def: PluginDefinition) -> List[Dict]:
    """扫描tasks目录，查找并返回公开的任务入口点信息。"""
    public_tasks_info = []
    for task_path in tasks_dir.rglob("*.yaml"):
        try:
            with open(task_path, 'r', encoding='utf-8') as f:
                # 只读取文件开头部分来检查meta块，避免加载整个大文件
                content_head = f.read(2048)  # 读取2KB足够了
                task_data = yaml.safe_load(content_head)

            if isinstance(task_data, dict) and 'meta' in task_data:
                meta = task_data['meta']
                if meta.get('entry_point') is True:
                    task_info = {
                        "title": meta.get("title", task_path.stem),
                        "description": meta.get("description", ""),
                        "file": str(task_path.relative_to(plugin_def.path)),
                        "icon": meta.get("icon")
                    }
                    public_tasks_info.append(task_info)
                    logger.debug(f"发现公开任务入口点: {task_info['title']} in {plugin_def.canonical_id}")
        except Exception as e:
            logger.warning(f"解析任务文件元数据失败 '{task_path.relative_to(plugin_def.path)}': {e}")
    return public_tasks_info


def _get_module_name_from_path(file_path: Path) -> str:
    if PROJECT_BASE_PATH is None:
        raise RuntimeError("Builder的PROJECT_BASE_PATH未被初始化。")
    try:
        relative_path = file_path.relative_to(PROJECT_BASE_PATH)
    except ValueError:
        relative_path = Path(file_path.name)
    return str(relative_path).replace('/', '.').replace('\\', '.').removesuffix('.py')


def _load_module_from_path(file_path: Path, module_name: str) -> Optional[Any]:
    if module_name in sys.modules:
        logger.info(f"模块 '{module_name}' 已在 sys.modules 中，直接返回。")
        return sys.modules[module_name]

    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None:
            logger.warning(f"无法为文件创建模块规范: {file_path}")
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        logger.info(f"已加载模块: {module_name}")
        return module
    except Exception:
        logger.error(f"从路径 '{file_path}' 加载模块时发生未知错误。", exc_info=True)
        if module_name in sys.modules:
            del sys.modules[module_name]
        raise
