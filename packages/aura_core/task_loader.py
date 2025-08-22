from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from cachetools import TTLCache
from cachetools.keys import hashkey

from packages.aura_core.logger import logger


class TaskLoader:
    """
    任务加载器。
    【Async Refactor】在加载任务时，自动填充默认的 'execution_mode'。
    """

    def __init__(self, plan_name: str, plan_path: Path):
        self.plan_name = plan_name
        self.tasks_dir = plan_path / "tasks"
        self.cache = TTLCache(maxsize=1024, ttl=300)

    def _load_and_parse_file(self, file_path: Path) -> Dict[str, Any]:
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

                # 【核心修改】为文件中的每个任务设置默认值
                for task_key, task_def in result.items():
                    if isinstance(task_def, dict):
                        task_def.setdefault('execution_mode', 'sync')

                self.cache[key] = result
                return result
            except Exception as e:
                logger.error(f"加载并解析任务文件 '{file_path}' 失败: {e}")
                return {}

    def get_task_data(self, task_name_in_plan: str) -> Optional[Dict[str, Any]]:
        parts = task_name_in_plan.split('/')
        if len(parts) < 1:
            return None

        file_path_part = "/".join(parts[:-1]) if len(parts) > 1 else parts[0]
        task_key = parts[-1]

        file_path = (self.tasks_dir / f"{file_path_part}.yaml").resolve()

        if file_path.is_file():
            all_tasks_in_file = self._load_and_parse_file(file_path)
            task_data = all_tasks_in_file.get(task_key)
            if isinstance(task_data, dict) and 'steps' in task_data:
                return task_data

        logger.warning(f"在方案 '{self.plan_name}' 中找不到任务定义: '{task_name_in_plan}' (尝试路径: {file_path})")
        return None

    def get_all_task_definitions(self) -> Dict[str, Any]:
        # ... (此方法逻辑不变) ...
        all_definitions = {}
        if not self.tasks_dir.is_dir():
            return {}

        for task_file_path in self.tasks_dir.rglob("*.yaml"):
            all_tasks_in_file = self._load_and_parse_file(task_file_path)
            relative_path_str = task_file_path.relative_to(self.tasks_dir).with_suffix('').as_posix()

            for task_key, task_definition in all_tasks_in_file.items():
                if isinstance(task_definition, dict) and 'steps' in task_definition:
                    task_id = f"{relative_path_str}/{task_key}"
                    all_definitions[task_id] = task_definition

        return all_definitions
