# -*- coding: utf-8 -*-
"""
包管理 CLI 工具

提供 package init/build/sync/validate/info 等命令
"""

import argparse
from pathlib import Path
import sys

# 添加父目录到 path 以便导入
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from packages.aura_core.packaging.manifest.generator import ManifestGenerator
from packages.aura_core.packaging.manifest.parser import ManifestParser


def cmd_init(args):
    """初始化新包（生成 manifest.yaml 模板）"""
    path = Path(args.package_path)

    # 创建目录结构
    path.mkdir(parents=True, exist_ok=True)
    (path / "src").mkdir(exist_ok=True)
    (path / "tasks").mkdir(exist_ok=True)
    (path / "config").mkdir(exist_ok=True)

    # 生成默认 manifest
    generator = ManifestGenerator(path)
    manifest_data = generator._create_default_manifest()
    generator.save(manifest_data)

    print(f"[OK] 包已初始化: {path}")


def cmd_build(args):
    """从装饰器生成 manifest.yaml"""
    path = Path(args.package_path)

    generator = ManifestGenerator(path)
    manifest_data = generator.generate(preserve_manual_edits=not args.force)
    generator.save(manifest_data)

    print(f"[OK] Manifest 已生成: {path / 'manifest.yaml'}")


def cmd_sync(args):
    """同步 manifest（保留手动编辑）"""
    path = Path(args.package_path)

    generator = ManifestGenerator(path)
    manifest_data = generator.generate(preserve_manual_edits=True)
    generator.save(manifest_data)

    print(f"[OK] Manifest 已同步: {path / 'manifest.yaml'}")


def cmd_validate(args):
    """验证 manifest.yaml 的有效性"""
    path = Path(args.package_path)
    manifest_path = path / "manifest.yaml"

    if not manifest_path.exists():
        print(f"[ERROR] manifest.yaml 不存在", file=sys.stderr)
        return

    try:
        manifest = ManifestParser.parse(manifest_path)
        errors = ManifestParser.validate(manifest)

        if errors:
            print(f"[ERROR] Manifest 验证失败:")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"[OK] Manifest 验证通过")

    except Exception as e:
        print(f"[ERROR] 解析失败: {e}", file=sys.stderr)


def cmd_info(args):
    """显示包信息"""
    path = Path(args.package_path)
    manifest_path = path / "manifest.yaml"

    if not manifest_path.exists():
        print(f"[ERROR] manifest.yaml 不存在", file=sys.stderr)
        return

    manifest = ManifestParser.parse(manifest_path)

    print(f"包名: {manifest.package.name}")
    print(f"版本: {manifest.package.version}")
    print(f"描述: {manifest.package.description}")
    print(f"\n导出:")
    print(f"  - 服务: {len(manifest.exports.services)}")
    print(f"  - 动作: {len(manifest.exports.actions)}")
    print(f"  - 任务: {len(manifest.exports.tasks)}")
    print(f"\n依赖:")
    for dep_name, dep_spec in manifest.dependencies.items():
        print(f"  - {dep_name} ({dep_spec.version})")


def main():
    parser = argparse.ArgumentParser(description='Aura 包管理工具')
    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # init 命令
    parser_init = subparsers.add_parser('init', help='初始化新包')
    parser_init.add_argument('package_path', help='包路径')
    parser_init.set_defaults(func=cmd_init)

    # build 命令
    parser_build = subparsers.add_parser('build', help='从装饰器生成 manifest.yaml')
    parser_build.add_argument('package_path', help='包路径')
    parser_build.add_argument('--force', action='store_true', help='强制覆盖（不保留手动编辑）')
    parser_build.set_defaults(func=cmd_build)

    # sync 命令
    parser_sync = subparsers.add_parser('sync', help='同步 manifest（保留手动编辑）')
    parser_sync.add_argument('package_path', help='包路径')
    parser_sync.set_defaults(func=cmd_sync)

    # validate 命令
    parser_validate = subparsers.add_parser('validate', help='验证 manifest.yaml')
    parser_validate.add_argument('package_path', help='包路径')
    parser_validate.set_defaults(func=cmd_validate)

    # info 命令
    parser_info = subparsers.add_parser('info', help='显示包信息')
    parser_info.add_argument('package_path', help='包路径')
    parser_info.set_defaults(func=cmd_info)

    args = parser.parse_args()

    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
