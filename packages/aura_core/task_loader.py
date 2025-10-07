"""
定义了 `TaskLoader`，一个负责从文件系统加载和解析任务定义的组件。

该模块的核心是 `TaskLoader` 类，它为每个方案（Plan）提供了一个专属的
任务加载器实例。它能够：
- 从方案的 `tasks` 目录中按需加载 YAML 文件。
- 使用带有时间过期（TTL）的缓存来优化文件读取性能。
- 解析 YAML 文件，并支持一个文件中定义多个任务的新格式。
- 为每个加载的任务自动填充默认的 `execution_mode`。
- 提供接口来获取单个任务的定义或方案内的所有任务定义。
"""
from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from cachetools import TTLCache
from cachetools.keys import hashkey

from packages.aura_core.logger import logger


class TaskLoader:
    """
    负责从文件系统加载、解析和缓存任务定义。

    每个 `Orchestrator` 拥有一个 `TaskLoader` 实例，用于处理其
    所属方案内的所有任务加载请求。
    """

    def __init__(self, plan_name: str, plan_path: Path):
        """
        初始化任务加载器。

        Args:
            plan_name (str): 当前加载器所属的方案名称。
            plan_path (Path): 当前方案的根目录路径。
        """
        self.plan_name = plan_name
        self.tasks_dir = plan_path / "tasks"
        self.cache = TTLCache(maxsize=1024, ttl=300)

    def _load_and_parse_file(self, file_path: Path) -> Dict[str, Any]:
        """
        加载并解析单个 YAML 任务文件，并应用缓存。

        此方法会为文件中的每个任务定义自动设置默认的 `execution_mode` 为 'sync'。

        Args:
            file_path (Path): 要加载的 YAML 文件的绝对路径。

        Returns:
            Dict[str, Any]: 一个包含文件中所有任务定义的字典。如果文件不存在或
                解析失败，则返回一个空字典。
        """
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

                # 为文件中的每个任务设置默认值
                for task_key, task_def in result.items():
                    if isinstance(task_def, dict):
                        task_def.setdefault('execution_mode', 'sync')

                self.cache[key] = result
                return result
            except Exception as e:
                logger.error(f"加载并解析任务文件 '{file_path}' 失败: {e}")
                return {}

    def get_task_data(self, task_name_in_plan: str) -> Optional[Dict[str, Any]]:
        """
        获取方案内指定任务的定义数据。

        此方法支持多级目录结构，例如 `subdir/mytask` 会被解析为
        在 `tasks/subdir.yaml` 文件中寻找名为 `mytask` 的任务定义。

        Args:
            task_name_in_plan (str): 任务在方案内的名称，可能包含路径。

        Returns:
            Optional[Dict[str, Any]]: 如果找到，则返回任务的定义字典；否则返回 None。
        """
        parts = task_name_in_plan.split('/')
        if not parts:
            return None

        # 如果任务名是 `a/b/c`，则文件是 `tasks/a/b.yaml`，任务键是 `c`
        file_path_part = "/".join(parts[:-1]) if len(parts) > 1 else parts[0]
        task_key = parts[-1]

        # 尝试直接匹配文件名
        file_path = (self.tasks_dir / f"{file_path_part}.yaml").resolve()
        if not file_path.is_file() and len(parts) == 1:
            # 如果是单层任务名，且找不到对应的 yaml 文件，则可能是旧格式，
            # 即文件名就是任务名，文件内没有任务键。
            # 但当前实现已统一为新格式，此处逻辑可简化或用于未来兼容。
            pass

        if file_path.is_file():
            all_tasks_in_file = self._load_and_parse_file(file_path)
            task_data = all_tasks_in_file.get(task_key)
            if isinstance(task_data, dict) and 'steps' in task_data:
                return task_data

        logger.warning(f"在方案 '{self.plan_name}' 中找不到任务定义: '{task_name_in_plan}' (尝试路径: {file_path})")
        return None

    def get_all_task_definitions(self) -> Dict[str, Any]:
        """
        获取当前方案中所有已发现的任务定义。

        此方法会遍历 `tasks` 目录下的所有 `.yaml` 文件，加载并返回
        一个从完整任务ID（`subdir/task_key`）到任务定义的字典。

        Returns:
            Dict[str, Any]: 包含所有任务定义的字典。
        """
        all_definitions = {}
        if not self.tasks_dir.is_dir():
            return {}

        for task_file_path in self.tasks_dir.rglob("*.yaml"):
            all_tasks_in_file = self._load_and_parse_file(task_file_path)
            relative_path_str = task_file_path.relative_to(self.tasks_dir).with_suffix('').as_posix()

            for task_key, task_definition in all_tasks_in_file.items():
                if isinstance(task_definition, dict) and 'steps' in task_definition:
                    # 组合成完整的任务ID，如 a/b/c (来自 a/b.yaml 的 c 任务)
                    task_id = f"{relative_path_str}/{task_key}"
                    all_definitions[task_id] = task_definition

        return all_definitions
