# packages/aura_shared_utils/models/plugin_definition.py

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

from packages.aura_shared_utils.utils.logger import logger


@dataclass
class Dependency:
    """代表一个插件依赖项。"""
    service: str
    from_plugin: str


@dataclass
class PluginDefinition:
    """【最终版】插件的完整定义，从 plugin.yaml 解析而来。"""

    # --- Identity ---
    author: str
    name: str

    # --- Metadata ---
    version: str
    description: str
    homepage: str

    # --- Structure ---
    path: Path  # 插件的根目录
    plugin_type: str  # core, official, third_party, plan

    # --- Dependencies & Extensions ---
    dependencies: Dict[str, str] = field(default_factory=dict)
    extends: List[Dependency] = field(default_factory=list)
    overrides: List[str] = field(default_factory=list)

    @property
    def canonical_id(self) -> str:
        """
        计算并返回插件的规范ID，格式为 'author/name'。
        这是插件在整个系统中的唯一标识符。
        """
        if not self.author or not self.name:
            return "N/A"
        return f"{self.author}/{self.name}"

    @classmethod
    def from_yaml(cls, data: Dict[str, Any], plugin_path: Path, plugin_type: str) -> 'PluginDefinition':
        """从解析的YAML数据创建PluginDefinition实例。"""
        author = data.get('author')
        name = data.get('name')

        if not author or not name:
            raise ValueError(f"插件 '{plugin_path}' 的 plugin.yaml 必须包含 'author' 和 'name' 字段。")

        # 解析 extends 字段
        extends_list = []
        for item in data.get('extends', []):
            if isinstance(item, dict) and 'service' in item and 'from' in item:
                extends_list.append(Dependency(service=item['service'], from_plugin=item['from']))
            else:
                logger.warning(f"在 '{plugin_path}' 中发现格式不正确的 'extends' 项: {item}")

        return cls(
            author=author,
            name=name,
            version=data.get('version', '0.0.0'),
            description=data.get('description', ''),
            homepage=data.get('homepage', ''),
            path=plugin_path,
            plugin_type=plugin_type,
            dependencies=data.get('dependencies', {}),
            extends=extends_list,
            overrides=data.get('overrides', [])
        )
