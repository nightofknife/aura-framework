# -*- coding: utf-8 -*-
"""Scheduler 工具函数模块

包含与调度器相关的辅助工具函数，这些函数相对独立，不依赖于Scheduler类的状态。
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Set
from packages.aura_core.packaging.core.dependency_manager import DependencyManager


def resolve_base_path() -> Path:
    """解析 Aura 框架的基础路径。

    优先级：
    1. 环境变量 AURA_BASE_PATH
    2. 如果是打包的可执行文件，使用可执行文件所在目录
    3. 否则使用当前文件的两级父目录

    Returns:
        Path: Aura 框架的基础路径
    """
    env_base = os.getenv("AURA_BASE_PATH")
    if env_base:
        return Path(env_base).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]  # 从 scheduler/utils.py 向上3级


def base36_encode(num: int) -> str:
    """将数字编码为 Base36 字符串。

    Args:
        num: 要编码的整数

    Returns:
        str: Base36 编码的字符串
    """
    if num == 0:
        return "0"
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = []
    n = num
    while n > 0:
        n, r = divmod(n, 36)
        out.append(chars[r])
    return "".join(reversed(out))


def short_cid_suffix(cid: Optional[str]) -> str:
    """从完整的 CID 提取短后缀（4个字符）。

    Args:
        cid: 完整的 CID 字符串

    Returns:
        str: 4个字符的后缀
    """
    if not cid:
        return "0000"
    try:
        return base36_encode(int(cid))[-4:].rjust(4, "0")
    except Exception:
        return (cid[-4:] if len(cid) >= 4 else cid.rjust(4, "0"))


def make_trace_id(plan_name: str, task_name: str, cid: str,
                  when: Optional[datetime] = None) -> str:
    """生成任务追踪ID。

    格式: {plan_name}/{task_name}@{timestamp}-{cid_suffix}
    例如: my_plan/my_task@260113-152030-A3F2

    Args:
        plan_name: Plan 名称
        task_name: 任务名称
        cid: 完整的执行 ID
        when: 时间戳（可选，默认当前时间）

    Returns:
        str: 追踪 ID
    """
    ts = when or datetime.now()
    time_part = ts.strftime("%y%m%d-%H%M%S")
    suffix = short_cid_suffix(cid)
    return f"{plan_name}/{task_name}@{time_part}-{suffix}"


def make_trace_label(plan_name: Optional[str], task_name: Optional[str],
                     all_tasks_definitions: dict) -> str:
    """生成任务追踪标签（带标题）。

    Args:
        plan_name: Plan 名称
        task_name: 任务名称
        all_tasks_definitions: 所有任务定义字典

    Returns:
        str: 任务标签（优先使用 meta.title，fallback 到 plan/task）
    """
    full_task_id = f"{plan_name}/{task_name}" if plan_name and task_name else (plan_name or task_name or "")
    task_def = all_tasks_definitions.get(full_task_id, {}) if full_task_id else {}
    title = task_def.get("meta", {}).get("title") if isinstance(task_def, dict) else None
    return title or full_task_id


def collect_requirement_names(req_file: Path, dep_mgr: DependencyManager) -> Set[str]:
    """读取 requirements 文件中的包名集合（小写），忽略无效行。

    Args:
        req_file: requirements 文件路径
        dep_mgr: 依赖管理器实例

    Returns:
        Set[str]: 包名集合（小写）
    """
    if not req_file.is_file():
        return set()
    try:
        requirements = dep_mgr._read_requirements(req_file)
    except Exception:
        return set()
    names: Set[str] = set()
    for req in requirements:
        name = getattr(req, "name", None)
        if name:
            names.add(name.lower())
    return names


def convert_task_reference_to_id(plan_name: str, task_ref: str) -> str:
    """
    将任务引用（新格式或旧格式）转换为标准任务ID，用于在 all_tasks_definitions 字典中查找。

    支持的格式：
    - 新格式: tasks:test:draw_one_star (语法糖，省略 .yaml)
    - 新格式: tasks:test:draw_one_star.yaml
    - 新格式: tasks:test:draw_one_star.yaml:custom_key
    - 旧格式: test/draw_one_star (简化格式，需要推断任务键)
    - 旧格式: test/draw_one_star/draw_one_star (完整格式)

    Args:
        plan_name: 计划名称
        task_ref: 任务引用字符串

    Returns:
        标准任务ID，格式为 "plan_name/path/file/task_key"
        例如: "MyTestPlan/test/draw_one_star/draw_one_star"
    """
    # 如果不包含冒号，说明可能是旧格式
    if ':' not in task_ref:
        # 旧格式有两种可能：
        # 1. test/draw_one_star/draw_one_star (完整格式，已包含任务键)
        # 2. test/draw_one_star (简化格式，需要推断任务键)

        parts = task_ref.split('/')
        if len(parts) >= 2:
            # 检查最后一部分是否与倒数第二部分相同
            if parts[-1] == parts[-2]:
                # 已经是完整格式，直接拼接
                return f"{plan_name}/{task_ref}"
            else:
                # 简化格式，假设任务键与文件名相同
                task_key = parts[-1]
                return f"{plan_name}/{task_ref}/{task_key}"
        else:
            # 单级路径，假设任务键与路径相同
            return f"{plan_name}/{task_ref}/{task_ref}"

    # 新格式: tasks:path1:path2:file 或 tasks:path1:path2:file:task_key
    parts = task_ref.split(':')

    # Remove leading 'tasks' segment if present
    if parts[0] == 'tasks':
        parts = parts[1:]

    # Empty path fallback
    if not parts:
        return f"{plan_name}/{task_ref}"

    # Locate explicit .yaml segment (file name)
    yaml_index = None
    for idx, part in enumerate(parts):
        if part.endswith('.yaml'):
            yaml_index = idx
            break

    if yaml_index is not None:
        # tasks:path:file.yaml or tasks:path:file.yaml:task_key
        file_parts = parts[:yaml_index + 1]
        file_parts[-1] = file_parts[-1].replace('.yaml', '')
        path = '/'.join(file_parts)
        if yaml_index + 1 < len(parts):
            task_key = parts[-1]
            return f"{plan_name}/{path}/{task_key}"
        # Default to same-name task key
        task_key = file_parts[-1]
        return f"{plan_name}/{path}/{task_key}"

    # No .yaml: treat last segment as task key
    if len(parts) >= 2:
        if len(parts) > 2:
            path = '/'.join(parts[:-1])
            task_key = parts[-1]
            return f"{plan_name}/{path}/{task_key}"
        path = '/'.join(parts)
        task_key = parts[-1]
        return f"{plan_name}/{path}/{task_key}"

    # Single segment fallback
    return f"{plan_name}/{parts[0]}/{parts[0]}"
