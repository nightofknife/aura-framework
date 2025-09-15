# src/aura_ide/panels/ide_panel/linter.py [V2 - v6 Graph-Aware]

from dataclasses import dataclass
from typing import List, Any, Optional

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


@dataclass
class LintingError:
    """封装一个Linter错误的信息"""
    line_number: int  # 行号 (从 1 开始)
    message: str
    severity: str = "error"  # 'error' or 'warning'


class Linter:
    """
    负责解析和验证Aura任务文件的内容。
    """

    def __init__(self):
        self._action_definitions: List[Any] = []
        self._action_map = {}
        self.yaml = YAML()

    def update_action_definitions(self, definitions: List[Any]):
        """更新Linter所知的Action定义"""
        self._action_definitions = definitions
        self._action_map = {d.name: d for d in definitions}

    def lint(self, text: str) -> List[LintingError]:
        """
        对给定的文本内容执行完整的检查，并返回错误列表。
        """
        errors: List[LintingError] = []

        # 1. 检查YAML语法是否有效
        try:
            data = self.yaml.load(text)
            if data is None:  # 空文件是有效的
                return []
        except YAMLError as e:
            line = e.problem_mark.line + 1 if e.problem_mark else 0
            message = f"YAML 语法错误: {e.problem}"
            return [LintingError(line_number=line, message=message)]

        # 2. 检查任务结构和逻辑
        if not isinstance(data, dict):
            errors.append(LintingError(line_number=1, message="YAML顶层应为字典结构 (任务名称: 任务定义)"))
            return errors

        for task_name, task_def in data.items():
            if not isinstance(task_def, dict) or 'steps' not in task_def:
                continue

            steps = task_def['steps']
            # 【修改】v6中steps是字典，不是列表
            if not isinstance(steps, dict):
                line = steps.lc.line if hasattr(steps, 'lc') else 0
                # 【修改】增加对旧版列表格式的兼容提示
                if isinstance(steps, list):
                    errors.append(
                        LintingError(line_number=line, message=f"检测到旧版v5线性steps列表。建议迁移到v6图结构。",
                                     severity="warning"))
                else:
                    errors.append(
                        LintingError(line_number=line, message=f"任务 '{task_name}' 的 'steps' 必须是一个字典"))
                continue

            # 【修改】遍历字典的键和值 (节点ID 和 节点定义)
            for node_id, step in steps.items():
                # 【新增】检查节点定义本身是否为字典
                if not isinstance(step, dict):
                    line = step.lc.line if hasattr(step, 'lc') else 0
                    errors.append(LintingError(line_number=line, message=f"节点 '{node_id}' 的定义必须是一个字典"))
                    continue

                step_line = step.lc.line if hasattr(step, 'lc') else 0

                # 检查 action 是否存在 (仅在简单节点中)
                action_name = step.get('action')
                if action_name:  # 如果存在 action 关键字
                    # 检查 action 名称是否合法
                    if action_name not in self._action_map:
                        # 尝试获取 'action' 关键字值的精确行号
                        action_line = step_line
                        if 'action' in step.lc.data:
                            action_line = step.lc.data['action'][2] + 1
                        errors.append(LintingError(line_number=action_line, message=f"未知的 Action: '{action_name}'"))
                        continue

                    # 检查 params
                    action_def = self._action_map[action_name]
                    valid_params = action_def.signature.parameters.keys()

                    if 'params' in step and isinstance(step['params'], dict):
                        for param_name in step['params'].keys():
                            if param_name not in valid_params:
                                param_line = step['params'].lc.data[param_name][0] + 1
                                errors.append(LintingError(
                                    line_number=param_line,
                                    message=f"Action '{action_name}' 不存在参数 '{param_name}'"
                                ))
        return errors
