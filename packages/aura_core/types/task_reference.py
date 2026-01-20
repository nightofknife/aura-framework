# -*- coding: utf-8 -*-
"""任务引用类型系统

此模块定义了任务引用的值对象（Value Object），用于在整个框架中统一表示任务路径。

设计原则：
1. 框架内部统一使用冒号格式表示任务路径
2. 只在读取文件时转换为斜杠路径
3. 不可变对象，线程安全
4. 提供清晰的API用于不同场景的格式转换

任务引用格式规范：
- 完整FQID: "作者名/包名/任务路径"
  例如: "cat/MyTestPlan/tasks:test:draw_multiple_stars"

- 相对引用: "任务路径" (省略作者名和包名)
  例如: "tasks:test:draw_multiple_stars"

- 任务路径: 使用冒号分隔的路径段
  例如: "tasks:test:draw_multiple_stars"
  对应文件: "tasks/test/draw_multiple_stars.yaml"

- 多任务文件引用: "任务路径:任务键"
  例如: "tasks:check_state:state_checks.yaml:is_in_receive_view"
  对应文件: "tasks/check_state/state_checks.yaml" 中的 "is_in_receive_view" 任务

文件后缀语义（三种）：
1. 无后缀: 执行文件中的第一个任务
   例如: "tasks:test:example" → 第一个任务
2. 有后缀: 执行同名任务（任务键与文件名相同）
   例如: "tasks:test:example.yaml" → 任务键为 "example" 的任务
3. 显式键: 执行指定任务
   例如: "tasks:test:example.yaml:task_b" → 任务键为 "task_b" 的任务
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Tuple, ClassVar
from functools import lru_cache
import re


@dataclass(frozen=True)
class TaskReference:
    """任务引用的值对象

    表示一个任务的标准化引用路径，支持完整FQID和相对路径两种形式。

    Attributes:
        author: 作者名（可选，相对路径时为None）
        package: 包名（必需）
        task_path: 任务路径，使用冒号分隔（必需）
        task_key: 任务键，用于指定YAML文件中的特定任务（可选）

    Examples:
        >>> # 完整FQID
        >>> ref = TaskReference.from_string("cat/MyTestPlan/tasks:test:draw_star")
        >>> ref.author
        'cat'
        >>> ref.package
        'MyTestPlan'
        >>> ref.task_path
        'tasks:test:draw_star'

        >>> # 相对路径
        >>> ref = TaskReference.from_string("tasks:test:draw_star", default_package="MyTestPlan")
        >>> ref.author
        None
        >>> ref.package
        'MyTestPlan'

        >>> # 转换为文件路径
        >>> ref.as_file_path()
        'tasks/test/draw_star.yaml'

        >>> # 转换为任务ID（用于字典键）
        >>> ref.as_id()
        'MyTestPlan/tasks:test:draw_star'
    """

    package: str
    task_path: str
    author: Optional[str] = None
    task_key: Optional[str] = None

    # 类级别的验证模式
    _VALID_PATH_PATTERN: ClassVar[re.Pattern] = re.compile(r'^[a-zA-Z0-9_:]+$')
    _VALID_NAME_PATTERN: ClassVar[re.Pattern] = re.compile(r'^[a-zA-Z0-9_-]+$')

    def __post_init__(self):
        """构造后立即验证"""
        self.validate()

    @classmethod
    def from_string(
        cls,
        ref: str,
        default_package: Optional[str] = None,
        default_author: Optional[str] = None
    ) -> TaskReference:
        """从字符串解析任务引用

        支持的格式：
        1. 完整FQID: "author/package/task:path"
        2. 包名+路径: "package/task:path"
        3. 相对路径: "task:path" (需要提供default_package)
        4. 多任务文件: "task:path:file.yaml:task_key"
        5. 向后兼容斜杠: "test/draw_star" (自动转换为冒号格式)

        Args:
            ref: 任务引用字符串
            default_package: 默认包名（用于相对路径）
            default_author: 默认作者名（可选）

        Returns:
            TaskReference实例

        Raises:
            ValueError: 如果引用格式无效或缺少必要参数

        Examples:
            >>> # 完整FQID
            >>> TaskReference.from_string("cat/MyTestPlan/tasks:test:draw_star")
            TaskReference(package='MyTestPlan', task_path='tasks:test:draw_star', author='cat')

            >>> # 相对路径
            >>> TaskReference.from_string("tasks:test:draw_star", default_package="MyTestPlan")
            TaskReference(package='MyTestPlan', task_path='tasks:test:draw_star', author=None)

            >>> # 多任务文件引用
            >>> TaskReference.from_string("tasks:check_state:state_checks.yaml:is_in_receive_view",
            ...                          default_package="MyTestPlan")
            TaskReference(package='MyTestPlan', task_path='tasks:check_state:state_checks.yaml',
                         task_key='is_in_receive_view')

            >>> # 向后兼容斜杠格式
            >>> TaskReference.from_string("test/draw_star", default_package="MyTestPlan")
            TaskReference(package='MyTestPlan', task_path='tasks:test:draw_star', author=None)
        """
        if not ref or not ref.strip():
            raise ValueError("Task reference cannot be empty")

        ref = ref.strip()
        author = None
        package = None
        task_path = None
        task_key = None

        # 步骤1: 检查是否包含斜杠（包前缀）
        if '/' in ref:
            parts = ref.split('/', 2)

            if len(parts) == 3:
                # 格式: author/package/task_path
                author, package, task_path = parts
            elif len(parts) == 2:
                # 格式: package/task_path
                # ❌ 拒绝旧格式斜杠（无冒号的路径）
                if ':' not in parts[1]:
                    raise ValueError(
                        f"Invalid task reference (use colon format): {ref}\n"
                        f"Expected format: 'package/tasks:test:example' or 'tasks:test:example'"
                    )
                package, task_path = parts
            else:
                raise ValueError(f"Invalid task reference format: {ref}")
        else:
            # 纯任务路径（相对引用）
            if not default_package:
                raise ValueError(
                    f"Relative task path '{ref}' requires default_package parameter"
                )
            package = default_package
            task_path = ref
            author = default_author

        # 步骤2: 处理任务键（多任务文件）
        # 格式: tasks:test:file.yaml:task_key
        if task_path and '.yaml:' in task_path:
            path_and_key = task_path.rsplit('.yaml:', 1)
            if len(path_and_key) == 2:
                task_path = path_and_key[0] + '.yaml'
                task_key = path_and_key[1]

        return cls(
            author=author if author else None,
            package=package,
            task_path=task_path,
            task_key=task_key if task_key else None
        )

    def infer_task_key(self) -> Optional[str]:
        """推断任务键基于文件后缀语义

        根据task_path是否包含.yaml后缀来推断任务键：
        - 如果有task_key: 返回显式指定的任务键
        - 如果task_path以.yaml结尾: 返回文件名作为任务键（同名任务）
        - 否则: 返回None（表示第一个任务）

        Returns:
            推断的任务键，或None表示执行第一个任务

        Examples:
            >>> # 显式任务键
            >>> ref = TaskReference(package="MyTestPlan", task_path="tasks:test:example.yaml", task_key="custom")
            >>> ref.infer_task_key()
            'custom'

            >>> # 有.yaml后缀 → 同名任务
            >>> ref = TaskReference(package="MyTestPlan", task_path="tasks:test:example.yaml")
            >>> ref.infer_task_key()
            'example'

            >>> # 无.yaml后缀 → 第一个任务
            >>> ref = TaskReference(package="MyTestPlan", task_path="tasks:test:example")
            >>> ref.infer_task_key()
            None
        """
        # 如果显式指定了任务键，直接返回
        if self.task_key:
            return self.task_key

        # 如果task_path以.yaml结尾，提取文件名作为任务键
        if self.task_path.endswith('.yaml'):
            # 移除.yaml后缀并按冒号分割，取最后一部分
            filename = self.task_path[:-5].split(':')[-1]
            return filename

        # 否则返回None，表示执行第一个任务
        return None

    def as_file_path(self, include_extension: bool = True) -> str:
        """转换为文件系统路径（斜杠格式）

        将冒号分隔的任务路径转换为文件系统路径。

        Args:
            include_extension: 是否包含.yaml扩展名（默认True）

        Returns:
            文件路径字符串

        Examples:
            >>> ref = TaskReference.from_string("tasks:test:draw_star", default_package="MyTestPlan")
            >>> ref.as_file_path()
            'tasks/test/draw_star.yaml'
            >>> ref.as_file_path(include_extension=False)
            'tasks/test/draw_star'
        """
        # 移除可能存在的.yaml后缀（避免重复）
        path = self.task_path
        if path.endswith('.yaml'):
            path = path[:-5]

        # 转换冒号为斜杠
        file_path = path.replace(':', '/')

        # 添加扩展名
        if include_extension:
            file_path += '.yaml'

        return file_path

    def as_fqid(self, include_author: bool = True) -> str:
        """转换为完整限定标识符（FQID）

        Args:
            include_author: 是否包含作者名（如果有）

        Returns:
            完整FQID字符串

        Examples:
            >>> ref = TaskReference(author="cat", package="MyTestPlan", task_path="tasks:test:draw_star")
            >>> ref.as_fqid()
            'cat/MyTestPlan/tasks:test:draw_star'
            >>> ref.as_fqid(include_author=False)
            'MyTestPlan/tasks:test:draw_star'
        """
        if include_author and self.author:
            return f"{self.author}/{self.package}/{self.task_path}"
        return f"{self.package}/{self.task_path}"

    def as_id(self) -> str:
        """转换为内部任务ID（用于字典键、日志等）

        格式: "package/task:path"

        Returns:
            任务ID字符串

        Examples:
            >>> ref = TaskReference(package="MyTestPlan", task_path="tasks:test:draw_star")
            >>> ref.as_id()
            'MyTestPlan/tasks:test:draw_star'
        """
        return f"{self.package}/{self.task_path}"

    def as_relative(self) -> str:
        """转换为相对路径（仅任务路径）

        Returns:
            相对路径字符串

        Examples:
            >>> ref = TaskReference(package="MyTestPlan", task_path="tasks:test:draw_star")
            >>> ref.as_relative()
            'tasks:test:draw_star'
        """
        return self.task_path

    def as_loader_path(self) -> str:
        """转换为TaskLoader期望的格式（斜杠分隔，移除tasks前缀）

        这是TaskLoader.get_task_data()方法期望的输入格式。
        使用infer_task_key()来确定是否添加任务键到路径末尾。

        Returns:
            TaskLoader格式的路径字符串

        Examples:
            >>> # 无后缀 → 第一个任务（不添加任务键）
            >>> ref = TaskReference(package="MyTestPlan", task_path="tasks:test:draw_star")
            >>> ref.as_loader_path()
            'test/draw_star'

            >>> # 有后缀 → 同名任务（添加推断的任务键）
            >>> ref = TaskReference(package="MyTestPlan", task_path="tasks:test:draw_star.yaml")
            >>> ref.as_loader_path()
            'test/draw_star/draw_star'

            >>> # 显式任务键
            >>> ref = TaskReference(package="MyTestPlan",
            ...                    task_path="tasks:check_state:state_checks.yaml",
            ...                    task_key="is_in_receive_view")
            >>> ref.as_loader_path()
            'check_state/state_checks/is_in_receive_view'
        """
        # 移除tasks前缀（如果有）
        path = self.task_path
        if path.startswith('tasks:'):
            path = path[6:]  # 移除 "tasks:"

        # 移除.yaml后缀
        if path.endswith('.yaml'):
            path = path[:-5]

        # 转换冒号为斜杠
        loader_path = path.replace(':', '/')

        # 使用infer_task_key()确定是否添加任务键
        inferred_key = self.infer_task_key()
        if inferred_key:
            loader_path = f"{loader_path}/{inferred_key}"

        return loader_path

    def as_dict_key(self) -> str:
        """转换为all_tasks_definitions字典键格式（斜杠分隔，移除tasks前缀）

        这是框架内部all_tasks_definitions字典使用的键格式。
        对于多任务文件，会在路径末尾添加任务键。

        Returns:
            字典键格式的路径字符串

        Examples:
            >>> # 单任务文件（语法糖：任务键与文件名相同）
            >>> ref = TaskReference(package="MyTestPlan", task_path="tasks:test:draw_star")
            >>> ref.as_dict_key()
            'test/draw_star/draw_star'

            >>> # 显式指定任务键
            >>> ref = TaskReference(package="MyTestPlan",
            ...                    task_path="tasks:test:draw_star",
            ...                    task_key="draw_star")
            >>> ref.as_dict_key()
            'test/draw_star/draw_star'

            >>> # 多任务文件
            >>> ref = TaskReference(package="MyTestPlan",
            ...                    task_path="tasks:check_state:state_checks.yaml",
            ...                    task_key="is_in_receive_view")
            >>> ref.as_dict_key()
            'check_state/state_checks/is_in_receive_view'
        """
        # 移除tasks前缀
        path = self.task_path
        if path.startswith('tasks:'):
            path = path[6:]

        # 移除.yaml后缀
        if path.endswith('.yaml'):
            path = path[:-5]

        # 转换冒号为斜杠
        dict_key = path.replace(':', '/')

        # 添加任务键
        if self.task_key:
            # 显式指定的任务键
            dict_key = f"{dict_key}/{self.task_key}"
        else:
            # 语法糖：推断任务键为文件名
            file_name = self.task_name
            dict_key = f"{dict_key}/{file_name}"

        return dict_key

    @property
    def path_parts(self) -> Tuple[str, ...]:
        """获取任务路径的各个部分

        Returns:
            路径部分的元组

        Examples:
            >>> ref = TaskReference.from_string("tasks:test:draw_star", default_package="MyTestPlan")
            >>> ref.path_parts
            ('tasks', 'test', 'draw_star')
        """
        # 移除可能的.yaml后缀
        path = self.task_path
        if path.endswith('.yaml'):
            path = path[:-5]
        return tuple(path.split(':'))

    @property
    def file_name(self) -> str:
        """获取文件名（带.yaml扩展名）

        Returns:
            文件名字符串

        Examples:
            >>> ref = TaskReference.from_string("tasks:test:draw_star", default_package="MyTestPlan")
            >>> ref.file_name
            'draw_star.yaml'
        """
        return self.path_parts[-1] + '.yaml'

    @property
    def directory(self) -> str:
        """获取目录路径（斜杠格式）

        Returns:
            目录路径字符串，如果只有一级路径则返回空字符串

        Examples:
            >>> ref = TaskReference.from_string("tasks:test:draw_star", default_package="MyTestPlan")
            >>> ref.directory
            'tasks/test'
            >>> ref2 = TaskReference.from_string("simple_task", default_package="MyTestPlan")
            >>> ref2.directory
            ''
        """
        parts = self.path_parts[:-1]
        return '/'.join(parts) if parts else ''

    @property
    def task_name(self) -> str:
        """获取任务名称（路径的最后一部分）

        Returns:
            任务名称字符串

        Examples:
            >>> ref = TaskReference.from_string("tasks:test:draw_star", default_package="MyTestPlan")
            >>> ref.task_name
            'draw_star'
        """
        return self.path_parts[-1]

    def with_package(self, package: str) -> TaskReference:
        """创建指定包的新引用（不可变模式）

        Args:
            package: 新的包名

        Returns:
            新的TaskReference实例

        Examples:
            >>> ref = TaskReference.from_string("tasks:test:draw_star", default_package="MyTestPlan")
            >>> ref2 = ref.with_package("AnotherPlan")
            >>> ref2.package
            'AnotherPlan'
            >>> ref.package  # 原对象不变
            'MyTestPlan'
        """
        return TaskReference(
            author=self.author,
            package=package,
            task_path=self.task_path,
            task_key=self.task_key
        )

    def with_author(self, author: Optional[str]) -> TaskReference:
        """创建指定作者的新引用（不可变模式）

        Args:
            author: 新的作者名

        Returns:
            新的TaskReference实例
        """
        return TaskReference(
            author=author,
            package=self.package,
            task_path=self.task_path,
            task_key=self.task_key
        )

    def with_task_key(self, task_key: Optional[str]) -> TaskReference:
        """创建指定任务键的新引用（不可变模式）

        Args:
            task_key: 新的任务键

        Returns:
            新的TaskReference实例
        """
        return TaskReference(
            author=self.author,
            package=self.package,
            task_path=self.task_path,
            task_key=task_key
        )

    def validate(self) -> None:
        """验证引用的有效性

        Raises:
            ValueError: 如果引用格式无效或包含非法字符
        """
        # 验证包名
        if not self.package:
            raise ValueError("Package name cannot be empty")
        if not self._VALID_NAME_PATTERN.match(self.package):
            raise ValueError(
                f"Invalid package name '{self.package}': "
                f"must contain only alphanumeric, underscore, and hyphen characters"
            )

        # 验证作者名（如果存在）
        if self.author and not self._VALID_NAME_PATTERN.match(self.author):
            raise ValueError(
                f"Invalid author name '{self.author}': "
                f"must contain only alphanumeric, underscore, and hyphen characters"
            )

        # 验证任务路径
        if not self.task_path:
            raise ValueError("Task path cannot be empty")

        # 安全检查：路径穿越（优先检查）
        if '..' in self.task_path:
            raise ValueError(
                f"Security: task path contains path traversal sequence '..': {self.task_path}"
            )

        # 安全检查：绝对路径（优先检查）
        if self.task_path.startswith('/') or self.task_path.startswith('\\'):
            raise ValueError(
                f"Security: task path cannot be an absolute path: {self.task_path}"
            )

        # 移除.yaml后缀后验证
        path_to_validate = self.task_path
        if path_to_validate.endswith('.yaml'):
            path_to_validate = path_to_validate[:-5]

        if not self._VALID_PATH_PATTERN.match(path_to_validate):
            raise ValueError(
                f"Invalid task path '{self.task_path}': "
                f"must contain only alphanumeric, underscore, and colon characters"
            )

        # 验证任务键（如果存在）
        if self.task_key and not self._VALID_NAME_PATTERN.match(self.task_key):
            raise ValueError(
                f"Invalid task key '{self.task_key}': "
                f"must contain only alphanumeric, underscore, and hyphen characters"
            )

    def __str__(self) -> str:
        """字符串表示（用于日志和调试）

        Returns:
            完整FQID（如果有作者）或任务ID
        """
        return self.as_fqid() if self.author else self.as_id()

    def __repr__(self) -> str:
        """详细表示（用于调试）"""
        return (
            f"TaskReference(package={self.package!r}, task_path={self.task_path!r}, "
            f"author={self.author!r}, task_key={self.task_key!r})"
        )

    def __hash__(self) -> int:
        """哈希值（用于字典键和集合）"""
        return hash((self.author, self.package, self.task_path, self.task_key))

    def __eq__(self, other: object) -> bool:
        """相等性比较"""
        if not isinstance(other, TaskReference):
            return NotImplemented
        return (
            self.author == other.author
            and self.package == other.package
            and self.task_path == other.task_path
            and self.task_key == other.task_key
        )


# 向后兼容的工具函数
def parse_task_reference(
    ref: str,
    default_package: Optional[str] = None,
    default_author: Optional[str] = None
) -> TaskReference:
    """解析任务引用字符串（便捷函数）

    这是TaskReference.from_string的别名，提供更简洁的调用方式。

    Args:
        ref: 任务引用字符串
        default_package: 默认包名
        default_author: 默认作者名

    Returns:
        TaskReference实例
    """
    return TaskReference.from_string(ref, default_package, default_author)
