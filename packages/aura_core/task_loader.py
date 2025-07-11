# packages/aura_core/task_loader.py (已修复缓存问题 - 最终版)

from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from cachetools import TTLCache
from cachetools.keys import hashkey  # 导入标准的键生成器

from packages.aura_shared_utils.utils.logger import logger


class TaskLoader:
    """
    任务加载器。
    负责从文件系统加载、解析并缓存方案包内的任务定义文件。
    """

    def __init__(self, plan_name: str, plan_path: Path):
        self.plan_name = plan_name
        self.tasks_dir = plan_path / "tasks"
        self.cache = TTLCache(maxsize=1024, ttl=300)

    # 【【【 Bug修复点 】】】
    # 彻底移除 @cached 装饰器，改为在方法内部手动实现缓存逻辑。
    # 这是处理每个实例拥有独立缓存的最可靠方法。
    def _load_and_parse_file(self, file_path: Path) -> Dict[str, Any]:
        """
        从单个YAML文件中加载所有任务定义。
        这个方法被手动缓存，以避免重复读取同一个文件。
        """
        # 1. 创建缓存键。对于实例方法，键必须只包含非 self 的参数。
        #    hashkey 会自动处理参数，但这里我们只有一个参数，所以直接用它创建元组也可以。
        key = hashkey(file_path)

        # 2. 尝试从缓存中获取数据
        try:
            return self.cache[key]
        except KeyError:
            # 3. 如果缓存中没有，则执行实际的加载逻辑
            if not file_path.is_file():
                # 即使文件不存在，也缓存这个“空”结果，避免短时间内重复检查
                self.cache[key] = {}
                return {}

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    result = data if isinstance(data, dict) else {}

                # 4. 将加载结果存入缓存
                self.cache[key] = result
                return result
            except Exception as e:
                logger.error(f"加载并解析任务文件 '{file_path}' 失败: {e}")
                # 发生错误时，不缓存结果，以便下次可以重试
                return {}

    def get_task_data(self, task_name_in_plan: str) -> Optional[Dict[str, Any]]:
        """
        根据方案内的任务ID获取任务定义。
        例如，对于 'quests/daily/main'，它会查找 'tasks/quests/daily.yaml' 文件，并提取 'main' 键。
        """
        parts = task_name_in_plan.split('/')

        # 至少要有一部分是文件名，一部分是任务键
        if len(parts) < 1:
            return None

        if len(parts) == 1:
            file_path_part = parts[0]
            task_key = parts[0]
        else:
            file_path_part = "/".join(parts[:-1])
            task_key = parts[-1]

        file_path = (self.tasks_dir / f"{file_path_part}.yaml").resolve()

        if file_path.is_file():
            all_tasks_in_file = self._load_and_parse_file(file_path)
            if task_key in all_tasks_in_file and isinstance(all_tasks_in_file.get(task_key), dict) and 'steps' in \
                    all_tasks_in_file[task_key]:
                return all_tasks_in_file[task_key]

        logger.warning(f"在方案 '{self.plan_name}' 中找不到任务定义: '{task_name_in_plan}' (尝试路径: {file_path})")
        return None

    def get_all_task_definitions(self) -> Dict[str, Any]:
        """
        加载并返回当前方案包内的所有任务定义，使用正确的ID格式。
        """
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
