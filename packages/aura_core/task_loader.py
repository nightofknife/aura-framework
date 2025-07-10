# packages/aura_core/task_loader.py (全新文件)

from pathlib import Path
from typing import Dict, Any, Optional
import yaml
from cachetools import cached, TTLCache

from packages.aura_shared_utils.utils.logger import logger


class TaskLoader:
    """
    任务加载器。
    负责从文件系统加载、解析并缓存方案包内的任务定义文件。
    """

    def __init__(self, plan_name: str, plan_path: Path):
        self.plan_name = plan_name
        self.tasks_dir = plan_path / "tasks"
        # 使用一个有时间限制的缓存，例如5分钟，以便在开发时修改任务能及时生效
        # maxsize=1024 意味着最多缓存1024个任务文件
        self.cache = TTLCache(maxsize=1024, ttl=300)

    @cached(cache='self.cache')
    def _load_and_parse_file(self, file_path: Path) -> Dict[str, Any]:
        """
        从单个YAML文件中加载所有任务定义。
        这个方法被缓存，以避免重复读取同一个文件。
        """
        if not file_path.is_file():
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except Exception as e:
            logger.error(f"加载并解析任务文件 '{file_path}' 失败: {e}")
            return {}

    def get_task_data(self, task_name_in_plan: str) -> Optional[Dict[str, Any]]:
        """
        获取指定任务的定义数据。
        它会智能地查找对应的YAML文件并从中提取任务。
        """
        # 尝试将任务名直接映射为文件名 (e.g., 'login' -> 'tasks/login.yaml')
        possible_file_path = (self.tasks_dir / f"{task_name_in_plan}.yaml").resolve()

        # 先检查直接映射的文件
        if possible_file_path.is_file():
            all_tasks_in_file = self._load_and_parse_file(possible_file_path)
            # 检查是否是旧的“单文件单任务”格式
            if 'steps' in all_tasks_in_file:
                return all_tasks_in_file
            # 否则，在文件中查找同名的任务key
            if task_name_in_plan in all_tasks_in_file:
                return all_tasks_in_file[task_name_in_plan]

        # 如果直接映射失败，则遍历所有文件查找 (处理 'user/create' -> 'tasks/user.yaml' 中的 'create' key)
        parts = task_name_in_plan.split('/')
        if len(parts) > 1:
            file_name = "/".join(parts[:-1]) + ".yaml"
            task_key = parts[-1]
            file_path = (self.tasks_dir / file_name).resolve()

            if file_path.is_file():
                all_tasks_in_file = self._load_and_parse_file(file_path)
                if task_key in all_tasks_in_file:
                    return all_tasks_in_file[task_key]

        logger.warning(f"在方案 '{self.plan_name}' 中找不到任务定义: '{task_name_in_plan}'")
        return None

    def get_all_task_definitions(self) -> Dict[str, Any]:
        """
        加载并返回当前方案包内的所有任务定义。
        """
        all_definitions = {}
        if not self.tasks_dir.is_dir():
            return {}

        for task_file_path in self.tasks_dir.rglob("*.yaml"):
            all_tasks_in_file = self._load_and_parse_file(task_file_path)

            # 旧格式: 'login.yaml' -> {'steps': ...}
            if 'steps' in all_tasks_in_file:
                relative_path = task_file_path.relative_to(self.tasks_dir)
                task_name_in_plan = relative_path.with_suffix('').as_posix()
                all_definitions[task_name_in_plan] = all_tasks_in_file
            # 新格式: 'user.yaml' -> {'create': {'steps':...}, 'delete': {'steps':...}}
            else:
                for task_key, task_definition in all_tasks_in_file.items():
                    if isinstance(task_definition, dict) and 'steps' in task_definition:
                        all_definitions[task_key] = task_definition

        return all_definitions

