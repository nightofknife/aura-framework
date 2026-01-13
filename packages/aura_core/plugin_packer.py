"""
插件打包工具

负责将插件打包为可分发的 .aura 文件
"""

from pathlib import Path
from typing import List
import zipfile
import tarfile
import subprocess
import logging
import fnmatch

from .plugin_manifest import PluginManifest
from .manifest_parser import ManifestParser

logger = logging.getLogger(__name__)


class PluginPacker:
    """插件打包工具"""

    def pack(self, plugin_dir: Path, output: str = None, format: str = "zip") -> Path:
        """打包插件"""
        # 1. 读取 manifest
        manifest_path = plugin_dir / "manifest.yaml"
        if not manifest_path.exists():
            raise ValueError("manifest.yaml not found")

        manifest = ManifestParser.parse(manifest_path)

        # 2. 确定输出文件名
        if output:
            output_file = Path(output)
        else:
            plugin_name = manifest.package.name.replace("@", "").replace("/", "-")
            output_file = Path.cwd() / f"{plugin_name}-{manifest.package.version}.aura"

        # 3. 执行 pre_build 脚本
        if manifest.build.scripts.get("pre_build"):
            self._run_script(plugin_dir, manifest.build.scripts["pre_build"])

        # 4. 收集文件
        files_to_pack = self._collect_files(plugin_dir, manifest)

        # 5. 打包
        if format == "zip":
            self._pack_zip(files_to_pack, output_file, plugin_dir)
        elif format == "tar.gz":
            self._pack_tar(files_to_pack, output_file, plugin_dir)

        # 6. 执行 post_build 脚本
        if manifest.build.scripts.get("post_build"):
            self._run_script(plugin_dir, manifest.build.scripts["post_build"])

        logger.info(f"✓ 插件已打包: {output_file}")
        return output_file

    def _collect_files(self, plugin_dir: Path, manifest: PluginManifest) -> List[Path]:
        """收集需要打包的文件"""
        files = []

        # 默认包含 manifest.yaml
        files.append(plugin_dir / "manifest.yaml")

        # 处理 include 规则
        for pattern in manifest.build.include:
            for file in plugin_dir.rglob("*"):
                if file.is_file() and fnmatch.fnmatch(str(file.relative_to(plugin_dir)), pattern):
                    files.append(file)

        # 处理 exclude 规则
        if manifest.build.exclude:
            filtered_files = []
            for file in files:
                rel_path = str(file.relative_to(plugin_dir))
                excluded = False
                for pattern in manifest.build.exclude:
                    if fnmatch.fnmatch(rel_path, pattern):
                        excluded = True
                        break
                if not excluded:
                    filtered_files.append(file)
            files = filtered_files

        return list(set(files))  # 去重

    def _pack_zip(self, files: List[Path], output_file: Path, base_dir: Path):
        """打包为 ZIP"""
        with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in files:
                arcname = file.relative_to(base_dir)
                zf.write(file, arcname)

    def _pack_tar(self, files: List[Path], output_file: Path, base_dir: Path):
        """打包为 tar.gz"""
        with tarfile.open(output_file, "w:gz") as tf:
            for file in files:
                arcname = file.relative_to(base_dir)
                tf.add(file, arcname)

    def _run_script(self, plugin_dir: Path, script: str):
        """执行脚本"""
        logger.info(f"Running script: {script}")
        result = subprocess.run(
            script,
            shell=True,
            cwd=plugin_dir,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Script failed: {result.stderr}")
        logger.info(result.stdout)
