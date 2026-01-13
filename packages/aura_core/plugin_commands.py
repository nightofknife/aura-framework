"""
插件管理 CLI 命令

提供完整的插件管理命令行接口
"""

import click
import os
import subprocess
from pathlib import Path
from typing import Optional

from .plugin_installer import PluginInstaller
from .plugin_packer import PluginPacker
from .plugin_manager_v2 import PluginManagerV2
from .config_manager import ConfigManager
from .plugin_scaffold import PluginScaffold


@click.group()
def plugin():
    """插件管理命令"""
    pass


@plugin.command()
@click.argument('source', type=click.Path(exists=True))
@click.option('--link', '-l', is_flag=True, help='创建符号链接而不是复制（开发模式）')
def install(source: str, link: bool):
    """
    从本地目录或压缩包安装插件

    示例:
        aura plugin install ./my-plugin
        aura plugin install ./my-plugin.zip
        aura plugin install /path/to/plugin --link
    """
    source_path = Path(source)
    installer = PluginInstaller()

    if link:
        success = installer.install_link(source_path)
    else:
        success = installer.install_local(source_path)

    if success:
        click.secho("✓ 插件安装成功", fg='green')
    else:
        click.secho("✗ 插件安装失败，请检查日志", fg='red')


@plugin.command()
@click.argument('plugin_id')
@click.option('--force', '-f', is_flag=True, help='强制卸载（即使被依赖）')
def uninstall(plugin_id: str, force: bool):
    """
    卸载插件

    示例:
        aura plugin uninstall @myorg/my-plugin
        aura plugin uninstall @myorg/my-plugin --force
    """
    installer = PluginInstaller()
    success = installer.uninstall(plugin_id, force=force)

    if success:
        click.secho("✓ 插件卸载成功", fg='green')
    else:
        click.secho("✗ 插件卸载失败，请检查日志", fg='red')


@plugin.command()
@click.option('--output', '-o', type=click.Path(), help='输出文件路径（默认: ./plugin-name.aura）')
@click.option('--format', type=click.Choice(['zip', 'tar.gz']), default='zip', help='打包格式')
def pack(output: Optional[str], format: str):
    """
    打包当前目录的插件为可分发文件

    示例:
        aura plugin pack
        aura plugin pack --output ~/my-plugin.aura
        aura plugin pack --format tar.gz
    """
    try:
        packer = PluginPacker()
        output_file = packer.pack(Path.cwd(), output, format)
        click.secho(f"✓ 插件已打包: {output_file}", fg='green')
    except Exception as e:
        click.secho(f"✗ 打包失败: {e}", fg='red')


@plugin.command()
def list():
    """列出已安装的插件"""
    pm = PluginManagerV2(Path("plans"))
    pm.load_all_plugins()

    if not pm.loaded_plugins:
        click.echo("没有已安装的插件")
        return

    click.echo("\n已安装的插件:\n")
    for plugin_id, manifest in pm.loaded_plugins.items():
        click.echo(f"  {plugin_id} v{manifest.package.version}")
        click.echo(f"    {manifest.package.description}")
        click.echo()


@plugin.command()
@click.argument('plugin_id')
def info(plugin_id: str):
    """查看插件详细信息"""
    pm = PluginManagerV2(Path("plans"))
    pm.load_all_plugins()

    if plugin_id not in pm.loaded_plugins:
        click.secho(f"插件 {plugin_id} 未安装", fg='red')
        return

    manifest = pm.loaded_plugins[plugin_id]

    click.echo(f"\n{manifest.package.name} v{manifest.package.version}")
    click.echo(f"描述: {manifest.package.description}")
    click.echo(f"许可证: {manifest.package.license}")

    if manifest.package.authors:
        click.echo(f"作者: {', '.join(a['name'] for a in manifest.package.authors)}")

    click.echo(f"\n依赖:")
    if manifest.dependencies:
        for dep_name, dep in manifest.dependencies.items():
            click.echo(f"  - {dep_name}: {dep.version}")
    else:
        click.echo("  无")

    click.echo(f"\n导出:")
    click.echo(f"  服务: {len(manifest.exports.services)}")
    click.echo(f"  动作: {len(manifest.exports.actions)}")
    click.echo(f"  任务: {len(manifest.exports.tasks)}")


@plugin.command()
@click.argument('plugin_id')
@click.option('--show', is_flag=True, help='显示当前配置')
@click.option('--export', is_flag=True, help='导出配置模板')
@click.option('--edit', is_flag=True, help='编辑用户配置')
@click.option('--validate', is_flag=True, help='验证配置')
@click.option('--output', '-o', type=click.Path(), help='导出配置到指定路径')
def config(plugin_id: str, show: bool, export: bool, edit: bool, validate: bool, output: Optional[str]):
    """
    管理插件配置

    示例:
        # 查看当前配置
        aura plugin config @myorg/my-plugin --show

        # 导出配置模板
        aura plugin config @myorg/my-plugin --export

        # 导出到指定路径
        aura plugin config @myorg/my-plugin --export --output ~/my-config.yaml

        # 编辑用户配置
        aura plugin config @myorg/my-plugin --edit

        # 验证配置
        aura plugin config @myorg/my-plugin --validate
    """
    pm = PluginManagerV2(Path("plans"))
    pm.load_all_plugins()

    if plugin_id not in pm.loaded_plugins:
        click.secho(f"插件 {plugin_id} 未安装", fg='red')
        return

    manifest = pm.loaded_plugins[plugin_id]
    config_mgr = ConfigManager(manifest)

    if show:
        # 显示合并后的配置
        import yaml
        merged_config = config_mgr.get_merged_config()
        click.echo("\n当前配置:\n")
        click.echo(yaml.dump(merged_config, allow_unicode=True, sort_keys=False))

    elif export:
        # 导出配置模板
        output_path = Path(output) if output else None
        exported_path = config_mgr.export_user_template(output_path)
        click.secho(f"✓ 配置模板已导出: {exported_path}", fg='green')

    elif edit:
        # 编辑用户配置
        plugin_name = manifest.package.name.replace("@", "").replace("/", "_")
        user_config_path = Path.home() / ".aura" / "plugins" / f"{plugin_name}.yaml"

        # 如果不存在，先导出
        if not user_config_path.exists():
            config_mgr.export_user_template()

        # 使用默认编辑器打开
        editor = os.environ.get('EDITOR', 'notepad' if os.name == 'nt' else 'nano')
        subprocess.run([editor, str(user_config_path)])

    elif validate:
        # 验证配置
        merged_config = config_mgr.get_merged_config()
        is_valid, errors = config_mgr.validate_config(merged_config)

        if is_valid:
            click.secho("✓ 配置验证通过", fg='green')
        else:
            click.secho("✗ 配置验证失败:", fg='red')
            for error in errors:
                click.echo(f"  - {error}")
    else:
        click.echo("请指定操作: --show, --export, --edit, --validate")


@plugin.command()
@click.option('--template', '-t', type=click.Choice(['basic', 'service', 'task', 'full']), default='basic')
@click.argument('name')
def init(template: str, name: str):
    """
    初始化新插件项目

    示例:
        aura plugin init @myorg/my-plugin
        aura plugin init my-plugin --template full
        aura plugin init @myorg/my-plugin --template service
    """
    try:
        scaffold = PluginScaffold()
        plugin_dir = scaffold.create(name, template)
        click.secho(f"✓ 插件项目已创建: {plugin_dir}", fg='green')
        click.echo(f"\n下一步:")
        click.echo(f"  cd {plugin_dir.name}")
        click.echo(f"  # 编辑 manifest.yaml 和源代码")
        click.echo(f"  aura plugin install . --link  # 开发模式安装")
    except Exception as e:
        click.secho(f"✗ 创建插件失败: {e}", fg='red')

