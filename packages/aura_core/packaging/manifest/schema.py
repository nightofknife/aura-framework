"""
插件清单数据类

定义插件的 manifest.yaml 的数据结构
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal, Any
from pathlib import Path
from packaging.specifiers import SpecifierSet
from packaging.version import Version


@dataclass
class PackageInfo:
    """插件包信息"""
    name: str  # @scope/name 格式
    version: str
    description: str
    license: str
    authors: List[Dict[str, str]] = field(default_factory=list)
    homepage: Optional[str] = None
    repository: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)

    @property
    def canonical_id(self) -> str:
        """规范化 ID (去除 @)"""
        return self.name.lstrip("@")


@dataclass
class DependencySpec:
    """依赖规范"""
    name: str
    version: str  # semver 约束
    source: Literal["local", "git"]
    path: Optional[Path] = None  # 本地路径
    git_url: Optional[str] = None
    git_ref: Optional[str] = None  # 分支/标签/commit
    optional: bool = False
    features: List[str] = field(default_factory=list)

    def is_version_compatible(self, version: str) -> bool:
        """检查版本是否兼容"""
        try:
            spec = SpecifierSet(self.version)
            return Version(version) in spec
        except Exception:
            return False


@dataclass
class ExportedService:
    """导出的服务"""
    name: str
    source: str  # module:class
    description: Optional[str] = None
    visibility: Literal["public", "private"] = "public"
    config_schema: Optional[Dict[str, Any]] = None


@dataclass
class ExportedAction:
    """导出的动作"""
    name: str
    source: str  # module:function
    description: Optional[str] = None
    visibility: Literal["public", "private"] = "public"
    parameters: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ExportedTask:
    """导出的任务"""
    id: str
    title: str
    source: str  # module:class
    description: Optional[str] = None
    visibility: Literal["public", "private"] = "public"
    schedule: Optional[str] = None
    config_template: Optional[str] = None


@dataclass
class Exports:
    """导出定义"""
    services: List[ExportedService] = field(default_factory=list)
    actions: List[ExportedAction] = field(default_factory=list)
    tasks: List[ExportedTask] = field(default_factory=list)


@dataclass
class LifecycleHooks:
    """生命周期钩子"""
    on_install: Optional[str] = None
    on_uninstall: Optional[str] = None
    on_load: Optional[str] = None
    on_unload: Optional[str] = None


@dataclass
class BuildConfig:
    """构建配置"""
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    scripts: Dict[str, str] = field(default_factory=dict)


@dataclass
class TrustInfo:
    """信任信息"""
    signature: Optional[Dict[str, str]] = None


@dataclass
class ConfigurationSpec:
    """配置规范"""
    default_config: Optional[str] = "config/default.yaml"
    config_schema: Optional[str] = "config/schema.json"
    user_template: Optional[str] = "config/template.yaml"
    allow_user_override: bool = True
    merge_strategy: Literal["merge", "replace"] = "merge"


@dataclass
class ResourceMapping:
    """资源文件映射"""
    templates: Dict[str, str] = field(default_factory=dict)
    data: Dict[str, str] = field(default_factory=dict)
    assets: Dict[str, str] = field(default_factory=dict)


@dataclass
class PluginManifest:
    """插件清单"""
    package: PackageInfo
    requires: Dict[str, str] = field(default_factory=dict)
    dependencies: Dict[str, DependencySpec] = field(default_factory=dict)
    pypi_dependencies: Dict[str, str] = field(default_factory=dict)
    exports: Exports = field(default_factory=Exports)
    extends: List[Dict[str, Any]] = field(default_factory=list)
    overrides: List[Dict[str, str]] = field(default_factory=list)
    lifecycle: LifecycleHooks = field(default_factory=LifecycleHooks)
    configuration: ConfigurationSpec = field(default_factory=ConfigurationSpec)
    resources: ResourceMapping = field(default_factory=ResourceMapping)
    build: BuildConfig = field(default_factory=BuildConfig)
    trust: TrustInfo = field(default_factory=TrustInfo)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 插件路径（加载时填充）
    path: Optional[Path] = None

    def is_compatible_with_aura(self, aura_version: str) -> bool:
        """检查是否兼容当前 Aura 版本"""
        constraint = self.requires.get("aura", "*")
        spec = SpecifierSet(constraint)
        return Version(aura_version) in spec

    def verify_signature(self) -> bool:
        """验证签名（可选）"""
        if not self.trust.signature:
            return True  # 无签名，默认信任（本地安装）

        # TODO: 实现签名验证逻辑
        return True

    # ========== 资源访问辅助方法 ==========

    def get_config_path(self, filename: str = None) -> Path:
        """获取配置文件路径"""
        if filename is None:
            filename = self.configuration.default_config
        return self.path / filename

    def get_template_path(self, name_or_path: str) -> Path:
        """获取模板文件路径（支持名称映射或直接路径）"""
        # 如果是映射的名称
        if name_or_path in self.resources.templates:
            return self.path / self.resources.templates[name_or_path]
        # 否则作为直接路径
        return self.path / name_or_path

    def get_data_path(self, name_or_path: str) -> Path:
        """获取数据文件路径"""
        if name_or_path in self.resources.data:
            return self.path / self.resources.data[name_or_path]
        return self.path / name_or_path

    def get_asset_path(self, name_or_path: str) -> Path:
        """获取资源文件路径"""
        if name_or_path in self.resources.assets:
            return self.path / self.resources.assets[name_or_path]
        return self.path / name_or_path

    def read_config(self, filename: str = None) -> dict:
        """读取配置文件"""
        import yaml
        config_path = self.get_config_path(filename)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}

    def read_template(self, name_or_path: str) -> str:
        """读取模板文件"""
        template_path = self.get_template_path(name_or_path)
        return template_path.read_text(encoding='utf-8')

    def read_data(self, name_or_path: str) -> Any:
        """读取数据文件（自动识别格式）"""
        import json
        import yaml

        data_path = self.get_data_path(name_or_path)
        with open(data_path, 'r', encoding='utf-8') as f:
            if data_path.suffix in ['.json']:
                return json.load(f)
            elif data_path.suffix in ['.yaml', '.yml']:
                return yaml.safe_load(f)
            else:
                return f.read()
