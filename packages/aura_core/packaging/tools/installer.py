"""
插件安装器

负责从本地目录、压缩包或 Git 仓库安装插件
"""

from pathlib import Path
from typing import Optional, List
import shutil
import zipfile
import tarfile
import logging

from ..manifest.schema import PluginManifest, DependencySpec
from ..manifest.parser import ManifestParser

logger = logging.getLogger(__name__)


class PluginInstaller:
    """本地插件安装器"""

    def __init__(self, plugins_dir: Path = None):
        self.plugins_dir = plugins_dir or Path("plans")
        self.plugins_dir.mkdir(exist_ok=True)

    def install_local(self, source: Path) -> bool:
        """从本地目录或压缩包安装插件"""
        try:
            # 1. 判断源类型
            if source.is_file():
                # 压缩包
                plugin_dir = self._extract_archive(source)
            elif source.is_dir():
                # 目录
                plugin_dir = source
            else:
                raise ValueError(f"Invalid source: {source}")

            # 2. 读取 manifest
            manifest_path = plugin_dir / "manifest.yaml"
            if not manifest_path.exists():
                raise ValueError("manifest.yaml not found in plugin")

            manifest = ManifestParser.parse(manifest_path)

            # 3. 验证 manifest
            errors = ManifestParser.validate(manifest)
            if errors:
                raise ValueError(f"Invalid manifest: {errors}")

            # 4. 检查是否已安装
            target_dir = self.plugins_dir / manifest.package.name.replace("@", "").replace("/", "_")
            if target_dir.exists():
                logger.warning(f"Plugin {manifest.package.name} already installed. Overwriting...")
                shutil.rmtree(target_dir)

            # 5. 复制插件文件
            if source.is_dir():
                shutil.copytree(plugin_dir, target_dir)
            else:
                # 已解压的临时目录，直接移动
                shutil.move(str(plugin_dir), str(target_dir))

            # 6. 安装依赖（递归）
            self._install_dependencies(manifest)

            # 7. 调用 on_install 钩子
            if manifest.lifecycle.on_install:
                self._call_hook(manifest, manifest.lifecycle.on_install)

            logger.info(f"✓ 插件 {manifest.package.name} 安装成功")
            return True

        except Exception as e:
            logger.error(f"✗ 插件安装失败: {e}")
            return False

    def install_link(self, source: Path) -> bool:
        """创建符号链接（开发模式）"""
        try:
            if not source.is_dir():
                raise ValueError("Link mode only supports directories")

            manifest_path = source / "manifest.yaml"
            if not manifest_path.exists():
                raise ValueError("manifest.yaml not found")

            manifest = ManifestParser.parse(manifest_path)
            target_dir = self.plugins_dir / manifest.package.name.replace("@", "").replace("/", "_")

            if target_dir.exists():
                if target_dir.is_symlink():
                    target_dir.unlink()
                else:
                    raise ValueError(f"Target {target_dir} exists and is not a symlink")

            target_dir.symlink_to(source.absolute())
            logger.info(f"✓ 插件 {manifest.package.name} 已链接（开发模式）")
            return True

        except Exception as e:
            logger.error(f"✗ 创建链接失败: {e}")
            return False

    def uninstall(self, plugin_id: str, force: bool = False) -> bool:
        """卸载插件"""
        try:
            # 1. 查找插件目录
            plugin_dir = self._find_plugin_dir(plugin_id)
            if not plugin_dir:
                logger.error(f"Plugin {plugin_id} not found")
                return False

            # 2. 读取 manifest
            manifest = ManifestParser.parse(plugin_dir / "manifest.yaml")

            # 3. 检查依赖（是否被其他插件依赖）
            if not force:
                dependents = self._find_dependents(plugin_id)
                if dependents:
                    logger.error(f"Plugin {plugin_id} is required by: {', '.join(dependents)}")
                    logger.error("Use --force to uninstall anyway")
                    return False

            # 4. 调用 on_uninstall 钩子
            if manifest.lifecycle.on_uninstall:
                self._call_hook(manifest, manifest.lifecycle.on_uninstall)

            # 5. 删除插件目录
            if plugin_dir.is_symlink():
                plugin_dir.unlink()
            else:
                shutil.rmtree(plugin_dir)

            logger.info(f"✓ 插件 {plugin_id} 已卸载")
            return True

        except Exception as e:
            logger.error(f"✗ 卸载失败: {e}")
            return False

    def _extract_archive(self, archive_path: Path) -> Path:
        """解压缩插件包"""
        import tempfile
        temp_dir = Path(tempfile.mkdtemp(prefix="aura_plugin_"))

        if archive_path.suffix == ".zip" or archive_path.name.endswith(".aura"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(temp_dir)
        elif archive_path.name.endswith(".tar.gz") or archive_path.suffix == ".tgz":
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(temp_dir)
        else:
            raise ValueError(f"Unsupported archive format: {archive_path}")

        # 查找 manifest.yaml（可能在子目录中）
        manifest_paths = list(temp_dir.rglob("manifest.yaml"))
        if not manifest_paths:
            raise ValueError("No manifest.yaml found in archive")

        return manifest_paths[0].parent

    def _install_dependencies(self, manifest: PluginManifest):
        """递归安装依赖"""
        for dep_name, dep in manifest.dependencies.items():
            if dep.optional:
                continue

            # 检查是否已安装
            if self._is_installed(dep_name):
                logger.info(f"Dependency {dep_name} already installed")
                continue

            logger.info(f"Installing dependency: {dep_name}")

            if dep.source == "local":
                # 本地依赖
                dep_path = manifest.path / dep.path
                self.install_local(dep_path)
            elif dep.source == "git":
                # Git 依赖（需要先克隆）
                self._install_from_git(dep)

    def _install_from_git(self, dep: DependencySpec):
        """从 Git 安装依赖"""
        import subprocess
        import tempfile

        temp_dir = Path(tempfile.mkdtemp(prefix=f"aura_git_{dep.name.replace('/', '_')}_"))

        try:
            # 克隆仓库
            cmd = ["git", "clone", "--depth", "1"]
            if dep.git_ref:
                cmd.extend(["--branch", dep.git_ref])
            cmd.extend([dep.git_url, str(temp_dir)])

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to clone {dep.git_url}: {result.stderr}")

            # 安装
            self.install_local(temp_dir)

        finally:
            # 清理
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    def _is_installed(self, plugin_id: str) -> bool:
        """检查插件是否已安装"""
        return self._find_plugin_dir(plugin_id) is not None

    def _find_plugin_dir(self, plugin_id: str) -> Optional[Path]:
        """查找插件目录"""
        # 尝试多种命名格式
        possible_names = [
            plugin_id.replace("@", "").replace("/", "_"),
            plugin_id.replace("@", "").replace("/", "-"),
            plugin_id.split("/")[-1] if "/" in plugin_id else plugin_id
        ]

        for name in possible_names:
            plugin_dir = self.plugins_dir / name
            if plugin_dir.exists() and (plugin_dir / "manifest.yaml").exists():
                return plugin_dir

        return None

    def _find_dependents(self, plugin_id: str) -> List[str]:
        """查找依赖此插件的其他插件"""
        dependents = []

        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            manifest_path = plugin_dir / "manifest.yaml"
            if not manifest_path.exists():
                continue

            try:
                manifest = ManifestParser.parse(manifest_path)
                for dep_name in manifest.dependencies.keys():
                    if dep_name.lstrip("@") == plugin_id.lstrip("@"):
                        dependents.append(manifest.package.canonical_id)
                        break
            except Exception:
                continue

        return dependents

    def _call_hook(self, manifest: PluginManifest, hook: str):
        """调用钩子函数"""
        try:
            # 解析钩子路径: module:function
            module_path, func_name = hook.split(':')

            # 动态导入模块
            import importlib
            import sys

            # 临时添加插件目录到 sys.path
            plugin_src_path = str(manifest.path / "src")
            if plugin_src_path not in sys.path:
                sys.path.insert(0, plugin_src_path)

            try:
                # 尝试直接导入（相对于 src 目录）
                module = importlib.import_module(module_path.replace('/', '.'))
                func = getattr(module, func_name)

                # 调用钩子函数
                logger.info(f"调用钩子: {hook}")
                func()

            finally:
                # 清理 sys.path
                if plugin_src_path in sys.path:
                    sys.path.remove(plugin_src_path)

        except Exception as e:
            logger.warning(f"调用钩子 {hook} 失败: {e}")
