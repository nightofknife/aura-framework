# -*- coding: utf-8 -*-
"""提供一个用于加载和缓存任务（Task）定义的加载器。

`TaskLoader` 负责从指定 Plan 的 `tasks` 目录中读取 YAML 文件，
解析出任务定义，并将其缓存起来以提高性能。它支持热重载，
可以在文件被修改时清除缓存，以便下次访问时能获取到最新的内容。
"""
from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from cachetools import TTLCache
from cachetools.keys import hashkey

from packages.aura_core.logger import logger
from packages.aura_core.config_loader import get_config_value
from packages.aura_core.schema_validator import validate_task_definition


class TaskLoader:
    """任务加载器。

    此类为每个 Plan 实例创建一个，负责加载该 Plan 内的所有任务定义。
    它使用一个带 TTL (Time-To-Live) 的缓存来避免频繁地读写磁盘。
    """

    def __init__(self, plan_name: str, plan_path: Path):
        """初始化任务加载器。

        Args:
            plan_name (str): 所属 Plan 的名称。
            plan_path (Path): 所属 Plan 的根目录路径。
        """
        self.plan_name = plan_name
        self.tasks_dir = plan_path / "tasks"
        cache_maxsize = int(get_config_value("task_loader.cache_maxsize", 1024))
        cache_ttl = int(get_config_value("task_loader.cache_ttl_sec", 300))
        self.cache = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)

        # Schema 验证配置
        self.enable_schema_validation = get_config_value("task_loader.enable_schema_validation", True)
        self.strict_validation = get_config_value("task_loader.strict_validation", False)

    def _load_and_parse_file(self, file_path: Path) -> Dict[str, Any]:
        """(私有) 加载并解析一个 YAML 文件，同时填充默认值并进行缓存。"""
        key = hashkey(file_path)
        try:
            return self.cache[key]
        except KeyError:
            if not file_path.is_file():
                self.cache[key] = {}
                return {}
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    result = data if isinstance(data, dict) else {}

                # Schema 验证（如果启用）
                if self.enable_schema_validation and result:
                    is_valid, error = validate_task_definition(result)
                    if not is_valid:
                        logger.error(f"任务文件 '{file_path.name}' Schema 验证失败: {error}")
                        if self.strict_validation:
                            # 严格模式：验证失败抛出异常
                            raise ValueError(f"Schema 验证失败: {error}")
                        else:
                            # 非严格模式：记录警告但继续执行
                            logger.warning(f"Schema 验证失败，但继续加载（非严格模式）")

                # 为文件中的每个任务设置默认的 'execution_mode'
                for task_def in result.values():
                    if isinstance(task_def, dict):
                        task_def.setdefault('execution_mode', 'sync')

                self.cache[key] = result
                return result
            except Exception as e:
                logger.error(f"加载并解析任务文件 '{file_path}' 失败: {e}")
                return {}

    def get_task_data(self, task_name_in_plan: str) -> Optional[Dict[str, Any]]:
        """根据任务在 Plan 内的名称获取其定义数据。

        此方法能处理多级目录结构，例如 `subdir/mytask` 会被解析为
        在 `tasks/subdir.yaml` 文件中寻找 `mytask` 这个键。

        Args:
            task_name_in_plan (str): 任务在 Plan 内的相对名称
                (e.g., "main_task" or "sub/other_task")。

        Returns:
            包含任务定义的字典，如果找不到则返回 None。
        """
        parts = task_name_in_plan.split('/')
        if not parts:
            return None

        task_key = parts[-1]

        # 优先尝试完整路径文件：tasks/a/b/c.yaml
        direct_path = self.tasks_dir.joinpath(*parts).with_suffix(".yaml")
        if direct_path.is_file():
            direct_data = self._load_and_parse_file(direct_path)
            if isinstance(direct_data, dict):
                if isinstance(direct_data.get('steps'), (list, dict)):
                    return self._normalize_task_concurrency(direct_data)
                task_data = direct_data.get(task_key)
                if isinstance(task_data, dict) and 'steps' in task_data:
                    return self._normalize_task_concurrency(task_data)

        # 兼容旧规则：tasks/a/b.yaml 内的 key=c
        file_path_parts = parts[:-1]
        if not file_path_parts:
            file_path_parts.append(task_key)
        file_path = self.tasks_dir.joinpath(*file_path_parts).with_suffix(".yaml")
        if file_path.is_file():
            all_tasks_in_file = self._load_and_parse_file(file_path)
            task_data = all_tasks_in_file.get(task_key)
            if isinstance(task_data, dict) and 'steps' in task_data:
                return self._normalize_task_concurrency(task_data)
            if isinstance(all_tasks_in_file, dict) and isinstance(all_tasks_in_file.get('steps'), (list, dict)):
                return self._normalize_task_concurrency(all_tasks_in_file)

        attempts = []
        if direct_path:
            attempts.append(str(direct_path))
        if file_path and str(file_path) not in attempts:
            attempts.append(str(file_path))
        logger.warning(
            f"在方案 '{self.plan_name}' 中找不到任务定义: '{task_name_in_plan}' "
            f"(尝试路径: {', '.join(attempts)})"
        )
        return None

    def _normalize_task_concurrency(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """规范化任务的并发配置。

        Args:
            task_data: 任务定义字典

        Returns:
            规范化后的任务定义（会修改原字典）
        """
        if not isinstance(task_data, dict):
            return task_data

        meta = task_data.get('meta', {})
        if not isinstance(meta, dict):
            return task_data

        concurrency = meta.get('concurrency')
        normalized = self._normalize_concurrency(concurrency)
        meta['__normalized_concurrency__'] = normalized

        return task_data

    def _normalize_concurrency(self, concurrency: Any) -> Dict[str, Any]:
        """规范化并发配置为统一格式。

        Args:
            concurrency: 原始并发配置（可以是 None, str, dict）

        Returns:
            规范化的并发配置字典:
            {
                'mode': 'exclusive' | 'concurrent' | 'shared',
                'resources': ['resource1', 'resource2:5'],
                'mutex_group': str or None,
                'max_instances': int or None
            }
        """
        # 默认值：独占模式（向后兼容）
        if concurrency is None:
            return {
                'mode': 'exclusive',
                'resources': [],
                'mutex_group': None,
                'max_instances': None
            }

        # 简化语法：concurrency: concurrent
        if isinstance(concurrency, str):
            return {
                'mode': concurrency,
                'resources': [],
                'mutex_group': None,
                'max_instances': None
            }

        # 完整语法
        if isinstance(concurrency, dict):
            mode = concurrency.get('mode')
            resources = concurrency.get('resources', [])
            mutex_group = concurrency.get('mutex_group')
            max_instances = concurrency.get('max_instances')

            # 简化语法：只有 resources（推断为 shared 模式）
            if not mode and resources:
                mode = 'shared'

            # 简化语法：只有 mutex_group（推断为 shared 模式）
            if not mode and mutex_group:
                mode = 'shared'

            # 如果还是没有 mode，默认为 shared
            if not mode:
                mode = 'shared'

            return {
                'mode': mode,
                'resources': resources if isinstance(resources, list) else [resources] if resources else [],
                'mutex_group': mutex_group,
                'max_instances': max_instances
            }

        # 无法识别，默认独占
        logger.warning(f"无法识别的并发配置格式: {concurrency}，使用默认独占模式")
        return self._normalize_concurrency(None)

    def get_all_task_definitions(self) -> Dict[str, Any]:
        """获取此 Plan 下所有已发现的任务定义。

        Returns:
            一个字典，键是任务在 Plan 内的完整名称，值是任务定义。
        """
        all_definitions = {}
        if not self.tasks_dir.is_dir():
            return {}

        for task_file_path in self.tasks_dir.rglob("*.yaml"):
            all_tasks_in_file = self._load_and_parse_file(task_file_path)
            relative_path_str = task_file_path.relative_to(self.tasks_dir).with_suffix('').as_posix()

            if isinstance(all_tasks_in_file, dict) and isinstance(all_tasks_in_file.get('steps'), (list, dict)):
                all_definitions[relative_path_str] = all_tasks_in_file
                continue

            for task_key, task_definition in all_tasks_in_file.items():
                if isinstance(task_definition, dict) and 'steps' in task_definition:
                    task_id = f"{relative_path_str}/{task_key}"
                    all_definitions[task_id] = task_definition
                    if task_key == Path(relative_path_str).name:
                        all_definitions.setdefault(relative_path_str, task_definition)

        return all_definitions

    def reload_task_file(self, file_path: Path) -> None:
        """重新加载或更新单个任务 YAML 文件中的定义。

        此方法的核心是清除该文件在缓存中的条目，这样下次访问时
        就会强制从磁盘重新加载。

        Args:
            file_path: 被修改的 YAML 文件的绝对路径。
        """
        key = hashkey(file_path)
        if key in self.cache:
            logger.info(f"[TaskLoader] 清除任务文件缓存: {file_path.name}")
            del self.cache[key]

        # 预热缓存，立即加载新内容以供后续使用
        self._load_and_parse_file(file_path)
        logger.info(f"[TaskLoader] 任务文件已重载: {file_path.name}")
