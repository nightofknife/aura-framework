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
        self.cache = TTLCache(maxsize=1024, ttl=300)

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

        # 如果任务名是 "a/b/c"，则文件是 "tasks/a/b.yaml"，键是 "c"
        # 如果任务名是 "a"，则文件是 "tasks/a.yaml"，键也是 "a"
        file_path_parts = parts[:-1]
        task_key = parts[-1]

        # 如果只有一个部分，它既是文件名也是任务键
        if not file_path_parts:
            file_path_parts.append(task_key)

        file_path = self.tasks_dir.joinpath(*file_path_parts).with_suffix(".yaml")

        if file_path.is_file():
            all_tasks_in_file = self._load_and_parse_file(file_path)
            task_data = all_tasks_in_file.get(task_key)
            if isinstance(task_data, dict) and 'steps' in task_data:
                return task_data

        logger.warning(f"在方案 '{self.plan_name}' 中找不到任务定义: '{task_name_in_plan}' (尝试路径: {file_path})")
        return None

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

            for task_key, task_definition in all_tasks_in_file.items():
                if isinstance(task_definition, dict) and 'steps' in task_definition:
                    # 组合路径和键来创建唯一的任务ID
                    task_id = f"{relative_path_str}/{task_key}"
                    all_definitions[task_id] = task_definition

        return all_definitions

    def reload_task_file(self, file_path: Path):
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