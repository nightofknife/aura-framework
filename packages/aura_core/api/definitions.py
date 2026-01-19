# -*- coding: utf-8 -*-
"""Aura 框架的核心数据定义。

此模块包含用于定义 Actions、Services 和 Hooks 的数据类。
"""
import inspect
import textwrap
from dataclasses import dataclass
from typing import Callable, Any, Dict, Optional, TYPE_CHECKING

from packages.aura_core.observability.logging.core_logger import logger

# 使用TYPE_CHECKING避免运行时循环导入
if TYPE_CHECKING:
    from ..packaging.manifest.schema import PluginManifest


@dataclass
class ActionDefinition:
    """封装一个已定义 Action 的所有元数据。

    Attributes:
        func (Callable): Action 对应的原始 Python 函数。
        name (str): Action 的名称,在 Plan 中通过此名称调用。
        read_only (bool): 标记此 Action 是否为只读。只读 Action 不应修改系统状态。
        public (bool): 标记此 Action 是否为公开 API,可被外部系统调用。
        service_deps (Dict[str, str]): 此 Action 依赖的服务及其别名。
        plugin (PluginManifest): 定义此 Action 的插件清单(✅ 统一为PluginManifest类型)。
        is_async (bool): 标记此 Action 的函数是否为异步 (`async def`)。
    """
    func: Callable
    name: str
    read_only: bool
    public: bool
    service_deps: Dict[str, str]
    plugin: 'PluginManifest'  # ✅ 统一类型注解
    is_async: bool = False

    @property
    def signature(self) -> inspect.Signature:
        """获取 Action 原始函数的签名。"""
        return inspect.signature(self.func)

    @property
    def docstring(self) -> str:
        """获取并格式化 Action 原始函数的文档字符串。"""
        doc = inspect.getdoc(self.func)
        return textwrap.dedent(doc).strip() if doc else "此行为没有提供文档说明。"

    @property
    def fqid(self) -> str:
        """获取此 Action 的完全限定ID (Fully Qualified ID)。

        ✅ 修复：统一使用三段式FQID: author/package/action
        只支持PluginManifest类型(新系统)
        """
        # 获取 canonical_id(格式: @author/package)
        canonical_id = self.plugin.package.canonical_id.lstrip('@')
        parts = canonical_id.split('/')

        if len(parts) == 2:
            author, package_name = parts
            return f"{author}/{package_name}/{self.name}"  # 三段式
        else:
            # 降级：不标准的canonical_id
            logger.warning(
                f"包 '{canonical_id}' 的 canonical_id 格式不标准，"
                f"应为 '@author/package'，生成的FQID可能不正确"
            )
            return f"{canonical_id}/{self.name}"


@dataclass
class ServiceDefinition:
    """封装一个已定义 Service 的所有元数据。

    Attributes:
        alias (str): 服务的短别名,用于依赖注入和覆盖。
        fqid (str): 服务的完全限定ID。
        service_class (type): 实现该服务的 Python 类。
        plugin (Optional[PluginManifest]): 定义此服务的包清单。核心服务此项为 None。
        public (bool): 标记此服务是否为公开,可被其他包扩展或覆盖。
        instance (Any): 服务被实例化后的单例对象。
        status (str): 服务的当前状态 (e.g., "defined", "resolving", "resolved", "failed")。
        is_extension (bool): 标记此服务是否是另一个服务的扩展。
        parent_fqid (Optional[str]): 如果是扩展,则为父服务的 FQID。
    """
    alias: str
    fqid: str
    service_class: type
    plugin: Optional['PluginManifest']
    public: bool
    instance: Any = None
    status: str = "defined"
    is_extension: bool = False
    parent_fqid: Optional[str] = None


@dataclass
class HookResult:
    """钩子执行结果。

    Attributes:
        func (Callable): 执行的钩子函数。
        ok (bool): 执行是否成功。
        result (Any): 执行结果。
        error (Optional[str]): 错误信息(如果失败)。
    """
    func: Callable
    ok: bool
    result: Any = None
    error: Optional[str] = None
