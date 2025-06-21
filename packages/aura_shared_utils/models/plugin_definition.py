# packages/aura_shared_utils/models/plugin_definition.py (修正版)

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
    path: Path
    plugin_type: str

    # --- Dependencies & Extensions ---
    dependencies: Dict[str, str] = field(default_factory=dict)
    extends: List[Dependency] = field(default_factory=list)
    overrides: List[str] = field(default_factory=list)

    @property
    def canonical_id(self) -> str:
        """计算并返回插件的规范ID，格式为 'author/name'。"""
        if not self.author or not self.name:
            return "N/A"
        return f"{self.author}/{self.name}"

    @classmethod
    def from_yaml(cls, data: Dict[str, Any], plugin_path: Path, plugin_type: str) -> 'PluginDefinition':
        """【已修正】从解析的YAML数据创建PluginDefinition实例。"""

        # 【核心修改】从 'identity' 字段下获取身份信息
        identity_data = data.get('identity', {})
        if not isinstance(identity_data, dict):
            raise ValueError(f"插件 '{plugin_path}' 的 plugin.yaml 中的 'identity' 字段必须是一个字典。")

        author = identity_data.get('author')
        name = identity_data.get('name')
        version = identity_data.get('version', '0.0.0')

        if not author or not name:
            # 【核心修改】提供更精确的错误信息
            raise ValueError(
                f"插件 '{plugin_path}' 的 plugin.yaml 中的 'identity' 字段下必须包含 'author' 和 'name' 子字段。")

        # 解析 extends 字段 (这部分逻辑保持不变)
        extends_list = []
        for item in data.get('extends', []):
            if isinstance(item, dict) and 'service' in item and 'from' in item:
                extends_list.append(Dependency(service=item['service'], from_plugin=item['from']))
            else:
                logger.warning(f"在 '{plugin_path}' 中发现格式不正确的 'extends' 项: {item}")

        return cls(
            author=author,
            name=name,
            version=version,  # 使用从 identity 中获取的版本
            description=data.get('description', ''),
            homepage=data.get('homepage', ''),
            path=plugin_path,
            plugin_type=plugin_type,
            dependencies=data.get('dependencies', {}),
            extends=extends_list,
            overrides=data.get('overrides', [])
        )
