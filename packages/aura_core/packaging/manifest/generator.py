# -*- coding: utf-8 -*-
"""
Manifest 生成器

从装饰器自动生成 manifest.yaml
"""

import inspect
from pathlib import Path
from typing import Dict, List, Any
import yaml

from packages.aura_core.observability.logging.core_logger import logger


class ManifestGenerator:
    """从装饰器生成 manifest.yaml"""

    def __init__(self, package_path: Path):
        self.package_path = package_path
        self.src_path = package_path / "src"
        self.tasks_path = package_path / "tasks"

    def generate(self, preserve_manual_edits: bool = True) -> Dict[str, Any]:
        """
        生成 manifest 数据

        Args:
            preserve_manual_edits: 是否保留用户手动编辑的字段

        Returns:
            完整的 manifest 数据字典
        """
        # 1. 读取现有 manifest（如果存在）
        existing_manifest = self._load_existing_manifest()

        # 2. 扫描装饰器
        services = self._scan_services()
        actions = self._scan_actions()
        tasks = self._scan_tasks()

        # 3. 构建新的 exports
        new_exports = {
            "services": services,
            "actions": actions,
            "tasks": tasks
        }

        # 4. 智能合并
        if preserve_manual_edits and existing_manifest:
            merged_manifest = self._merge_manifests(
                existing_manifest,
                new_exports
            )
        else:
            merged_manifest = existing_manifest or self._create_default_manifest()
            merged_manifest["exports"] = new_exports

        return merged_manifest

    def _load_existing_manifest(self) -> Dict[str, Any]:
        """加载现有 manifest"""
        manifest_path = self.package_path / "manifest.yaml"
        if manifest_path.exists():
            with open(manifest_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}

    def _create_default_manifest(self) -> Dict[str, Any]:
        """创建默认 manifest 结构"""
        return {
            "package": {
                "name": f"@{self.package_path.parent.name}/{self.package_path.name}",
                "version": "0.1.0",
                "description": "",
                "license": "MIT"
            },
            "requires": {
                "aura": ">=2.0.0"
            },
            "dependencies": {},
            "pypi-dependencies": {},
            "exports": {
                "services": [],
                "actions": [],
                "tasks": []
            }
        }

    def _scan_services(self) -> List[Dict[str, Any]]:
        """扫描 src/ 目录下的所有 @register_service"""
        services = []

        if not self.src_path.exists():
            return services

        for py_file in self.src_path.rglob("*.py"):
            # 动态导入模块
            module = self._import_module_from_path(py_file)
            if not module:
                continue

            # 查找所有类
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if hasattr(obj, '__aura_service__'):
                    meta = obj.__aura_service__

                    # 计算相对路径
                    rel_path = py_file.relative_to(self.src_path)
                    module_path = str(rel_path.with_suffix('')).replace('\\', '/')

                    services.append({
                        "name": meta["alias"],  # 使用 alias 作为 name
                        "source": f"{module_path}:{meta['source_class']}",
                        "description": meta["description"],
                        "visibility": meta.get("visibility", "public")
                    })

        return services

    def _scan_actions(self) -> List[Dict[str, Any]]:
        """扫描 src/ 目录下的所有 @register_action"""
        actions = []

        if not self.src_path.exists():
            return actions

        for py_file in self.src_path.rglob("*.py"):
            module = self._import_module_from_path(py_file)
            if not module:
                continue

            # 查找所有函数
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if hasattr(obj, '__aura_action__'):
                    meta = obj.__aura_action__

                    rel_path = py_file.relative_to(self.src_path)
                    module_path = str(rel_path.with_suffix('')).replace('\\', '/')

                    action_def = {
                        "name": meta["name"],
                        "source": f"{module_path}:{meta['source_function']}",
                        "description": meta["description"],
                        "visibility": meta.get("visibility", "public"),
                        "parameters": meta["parameters"]
                    }

                    # 添加可选字段
                    if meta.get("timeout"):
                        action_def["timeout"] = meta["timeout"]

                    actions.append(action_def)

        return actions

    def _scan_tasks(self) -> List[Dict[str, Any]]:
        """扫描 tasks/ 目录下的所有 .yaml 文件"""
        tasks = []

        if not self.tasks_path.exists():
            return tasks

        for yaml_file in self.tasks_path.glob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    task_data = yaml.safe_load(f)

                rel_path = yaml_file.relative_to(self.package_path)

                tasks.append({
                    "id": task_data.get("name", yaml_file.stem),
                    "title": task_data.get("description", ""),
                    "source": str(rel_path).replace('\\', '/'),
                    "description": task_data.get("description", "")
                })
            except Exception as e:
                logger.warning(f"扫描任务文件 {yaml_file} 失败: {e}")

        return tasks

    def _merge_manifests(
        self,
        existing: Dict[str, Any],
        new_exports: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        智能合并 manifest

        策略：
        1. package/requires/dependencies 等手动字段：保留现有值
        2. exports 字段：用新生成的覆盖，但保留用户添加的高级字段
        """
        merged = existing.copy()

        # 合并 exports
        merged["exports"] = {}

        for export_type in ["services", "actions", "tasks"]:
            new_items = new_exports.get(export_type, [])
            existing_items = existing.get("exports", {}).get(export_type, [])

            # 创建名称到现有项的映射
            if export_type == "tasks":
                existing_map = {item.get("id", item.get("name")): item for item in existing_items}
            else:
                existing_map = {item["name"]: item for item in existing_items}

            merged_items = []
            for new_item in new_items:
                # 获取唯一标识
                if export_type == "tasks":
                    key = new_item.get("id", new_item.get("name"))
                else:
                    key = new_item["name"]

                if key in existing_map:
                    # 存在旧项，合并
                    old_item = existing_map[key]
                    merged_item = new_item.copy()

                    # 保留用户手动添加的字段
                    for k, v in old_item.items():
                        if k not in new_item:
                            merged_item[k] = v

                    merged_items.append(merged_item)
                else:
                    # 新项
                    merged_items.append(new_item)

            merged["exports"][export_type] = merged_items

        return merged

    def _import_module_from_path(self, py_file: Path):
        """动态导入 Python 模块"""
        import sys
        import importlib.util

        spec = importlib.util.spec_from_file_location("temp_module", py_file)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)

        # 临时添加包路径到 sys.path
        package_root = str(self.package_path)
        if package_root not in sys.path:
            sys.path.insert(0, package_root)

        try:
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            logger.warning(f"导入模块 {py_file} 失败: {e}")
            return None
        finally:
            if package_root in sys.path:
                sys.path.remove(package_root)

    def save(self, manifest_data: Dict[str, Any]):
        """保存 manifest 到文件"""
        manifest_path = self.package_path / "manifest.yaml"

        with open(manifest_path, 'w', encoding='utf-8') as f:
            yaml.dump(
                manifest_data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False
            )

        logger.info(f"Manifest 已保存到 {manifest_path}")
