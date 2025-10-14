# -*- coding: utf-8 -*-
"""定义了 Aura 插件的数据模型。

此模块包含用于表示插件及其依赖关系的 `dataclasses`。
`PluginDefinition` 类是核心，它封装了从每个插件目录下的 `plugin.yaml`
文件中解析出来的所有信息。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any

from packages.aura_core.logger import logger


@dataclass
class Dependency:
    """代表一个插件对另一个插件中特定服务的扩展（`extends`）依赖。

    Attributes:
        service (str): 被扩展的服务的别名。
        from_plugin (str): 提供该服务的插件的规范ID (`author/name`)。
    """
    service: str
    from_plugin: str


@dataclass
class PluginDefinition:
    """一个插件的完整定义，通常从 `plugin.yaml` 文件解析而来。

    此类集成了插件的所有元数据、结构信息和依赖关系。

    Attributes:
        author (str): 插件的作者。
        name (str): 插件的名称。
        version (str): 插件的版本号。
        description (str): 插件功能的简要描述。
        homepage (str): 插件的主页或代码仓库 URL。
        path (Path): 插件在文件系统中的根目录路径。
        plugin_type (str): 插件的类型，例如 'plan' 或 'library'。
        dependencies (Dict[str, str]): 插件的外部 Python 包依赖。
        extends (List[Dependency]): 此插件扩展的其他服务的列表。
        overrides (List[str]): 被此插件完全覆盖的其他服务的 FQID 列表。
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
        """计算并返回插件的规范ID。

        规范ID是插件在整个框架中的唯一标识符，格式为 `author/name`。

        Returns:
            插件的规范ID字符串。如果作者或名称缺失，则返回 "N/A"。
        """
        if not self.author or not self.name:
            return "N/A"
        return f"{self.author}/{self.name}"

    @classmethod
    def from_yaml(cls, data: Dict[str, Any], plugin_path: Path, plugin_type: str) -> 'PluginDefinition':
        """从解析后的 YAML 数据创建 `PluginDefinition` 实例。

        这是一个工厂方法，负责将从 `plugin.yaml` 文件读取的字典数据
        转换为一个结构化的 `PluginDefinition` 对象。

        Args:
            data (Dict[str, Any]): 从 YAML 文件解析出的数据字典。
            plugin_path (Path): 插件的根目录路径。
            plugin_type (str): 插件的类型。

        Returns:
            一个 `PluginDefinition` 实例。

        Raises:
            ValueError: 如果 YAML 数据中缺少必要的字段（如 `identity.author`
                        或 `identity.name`）。
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
