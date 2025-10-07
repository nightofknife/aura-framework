"""
定义了 Aura 插件的核心数据结构。

该模块提供了 `Dependency` 和 `PluginDefinition` 两个数据类，
它们用于以结构化的方式表示从插件的 `plugin.yaml` 清单文件中
解析出来的信息。这是框架理解和管理插件的基础。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Type, TypeVar

from packages.aura_core.logger import logger

T = TypeVar('T', bound='PluginDefinition')


@dataclass
class Dependency:
    """
    代表一个插件对另一个插件提供的服务的依赖（特指继承关系）。

    Attributes:
        service (str): 被继承的服务（子服务）的别名。
        from_plugin (str): 提供该服务（父服务）的插件的规范ID (`author/name`)。
    """
    service: str
    from_plugin: str


@dataclass
class PluginDefinition:
    """
    一个插件的完整定义，通常从其 `plugin.yaml` 文件解析而来。

    这个数据类聚合了关于插件的所有元数据、结构信息和依赖关系。

    Attributes:
        author (str): 插件作者。
        name (str): 插件名称。
        version (str): 插件的版本号。
        description (str): 插件的简短描述。
        homepage (str): 插件的主页URL。
        path (Path): 插件在文件系统中的根目录路径。
        plugin_type (str): 插件的类型，例如 'plan', 'core', 'custom'。
        dependencies (Dict[str, str]): 插件的依赖项，格式为 `{'plugin_id': 'version_spec'}`。
        extends (List[Dependency]): 插件继承的服务列表。
        overrides (List[str]): 插件显式覆盖的其他插件的服务列表。
    """
    # --- 身份信息 ---
    author: str
    name: str

    # --- 元数据 ---
    version: str
    description: str
    homepage: str

    # --- 结构信息 ---
    path: Path
    plugin_type: str

    # --- 依赖与扩展 ---
    dependencies: Dict[str, str] = field(default_factory=dict)
    extends: List[Dependency] = field(default_factory=list)
    overrides: List[str] = field(default_factory=list)

    @property
    def canonical_id(self) -> str:
        """
        计算并返回插件的规范ID，格式为 'author/name'。

        这是插件在整个系统中的唯一标识符。

        Returns:
            str: 规范ID字符串，如果作者或名称为空，则返回 "N/A"。
        """
        if not self.author or not self.name:
            return "N/A"
        return f"{self.author}/{self.name}"

    @classmethod
    def from_yaml(cls: Type[T], data: Dict[str, Any], plugin_path: Path, plugin_type: str) -> T:
        """
        从解析后的 YAML 数据创建一个 PluginDefinition 实例。

        这是一个工厂方法，负责将从 `plugin.yaml` 文件读取的字典数据
        转换为一个结构化的 `PluginDefinition` 对象。

        Args:
            data (Dict[str, Any]): 从 YAML 文件解析出的字典数据。
            plugin_path (Path): 插件的根目录路径。
            plugin_type (str): 插件的类型。

        Returns:
            PluginDefinition: 一个新的 `PluginDefinition` 实例。

        Raises:
            ValueError: 如果 `identity` 字段缺失或其下的 `author` 或 `name` 字段缺失。
        """
        identity_data = data.get('identity', {})
        if not isinstance(identity_data, dict):
            raise ValueError(f"插件 '{plugin_path}' 的 plugin.yaml 中的 'identity' 字段必须是一个字典。")

        author = identity_data.get('author')
        name = identity_data.get('name')
        version = identity_data.get('version', '0.0.0')

        if not author or not name:
            raise ValueError(
                f"插件 '{plugin_path}' 的 plugin.yaml 中的 'identity' 字段下必须包含 'author' 和 'name' 子字段。")

        # 解析 'extends' 字段
        extends_list = []
        for item in data.get('extends', []):
            if isinstance(item, dict) and 'service' in item and 'from' in item:
                extends_list.append(Dependency(service=item['service'], from_plugin=item['from']))
            else:
                logger.warning(f"在 '{plugin_path}' 中发现格式不正确的 'extends' 项: {item}")

        return cls(
            author=author,
            name=name,
            version=version,
            description=data.get('description', ''),
            homepage=data.get('homepage', ''),
            path=plugin_path,
            plugin_type=plugin_type,
            dependencies=data.get('dependencies', {}),
            extends=extends_list,
            overrides=data.get('overrides', [])
        )
