# -*- coding: utf-8 -*-
"""Aura 框架的命令行接口 (CLI)。

该模块使用 `click` 库构建了一个功能丰富的命令行工具，用于与 Aura 框架进行交互。
它允许开发者管理插件包、运行临时任务以及检查已注册的服务。

主要命令组:
- `package`: 用于管理 Aura 包（插件），如构建。
- `task`: 用于运行和管理任务。
- `service`: 用于查看已注册的服务及其状态。

所有命令在执行前都会确保 Aura 核心框架（Scheduler）已被初始化。
"""
import click
import sys
from pathlib import Path

# --- 核心初始化 ---
# 为了让CLI能够访问框架的所有功能，我们需要在命令执行前加载整个框架。
# 这意味着我们需要能够导入Scheduler。为了确保路径正确，我们先将项目根目录添加到sys.path。
# 这种方式确保无论你在哪个目录下执行 `python cli.py ...`，导入都能正常工作。
try:
    # 将项目根目录添加到Python路径
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # 现在可以安全地导入Scheduler了
    from packages.aura_core.scheduler import Scheduler
    from packages.aura_core.observability.logging.core_logger import logger
    from packages.aura_core.plugin_commands import plugin as plugin_group
except ImportError as e:
    print(f"错误: 无法导入Aura核心模块。请确保你在项目根目录下运行此脚本，并且所有依赖都已安装。")
    print(f"原始错误: {e}")
    sys.exit(1)

# --- 全局框架实例 ---
# 在CLI脚本的生命周期内，我们只实例化一次Scheduler，以便所有命令共享同一个加载好的框架状态。
scheduler_instance: Scheduler = None


def get_scheduler() -> Scheduler:
    """获取全局的 Scheduler 实例，如果不存在则进行初始化。

    这是一个单例模式的实现，确保所有 CLI 命令共享同一个框架实例。
    首次调用时，它会实例化 Scheduler，这个过程会加载所有插件和定义。

    Returns:
        Scheduler: 全局唯一的调度器实例。

    Raises:
        SystemExit: 如果初始化过程中发生严重错误，则会终止程序。
    """
    global scheduler_instance
    if scheduler_instance is None:
        click.echo("正在初始化Aura框架...")
        try:
            scheduler_instance = Scheduler()
            click.echo("框架初始化完毕。\n")
        except Exception as e:
            logger.critical(f"初始化Aura框架失败: {e}", exc_info=True)
            click.secho(f"错误: 初始化Aura框架失败，请检查日志获取详细信息。", fg='red')
            sys.exit(1)
    return scheduler_instance


# --- CLI 命令定义 ---

@click.group()
def aura():
    """Aura 3.0 自动化框架命令行工具。

    这是所有命令的根入口点。调用任何子命令之前，它会通过 `get_scheduler()`
    确保 Aura 框架核心已经被加载。
    """
    # 这个函数是所有命令的入口，我们在这里确保框架被加载。
    get_scheduler()
    pass


# --- 1. 包管理命令组 ---
@aura.group()
def package():
    """管理 Aura 包（插件）的命令组。

    提供用于创建、构建、检查和管理 Aura 插件包的子命令。
    """
    pass


@package.command()
@click.argument('package_path', type=click.Path(exists=True, file_okay=False, resolve_path=True))
def build(package_path: str):
    """构建包 - 此功能已废弃。

    新架构使用 manifest.yaml 而不是 api.yaml。
    请手动创建 manifest.yaml 文件来定义包元数据。

    Args:
        package_path (str): 包的根目录路径。
    """
    click.secho("⚠️  包构建功能已废弃", fg='yellow')
    click.echo()
    click.echo("新架构使用 manifest.yaml 来定义插件元数据，不再需要从源码构建 api.yaml。")
    click.echo()
    click.echo("如需创建新包，请手动创建包含以下文件的目录结构：")
    click.echo("  - manifest.yaml  (包元数据)")
    click.echo("  - actions/       (动作定义)")
    click.echo("  - services/      (服务定义)")
    click.echo("  - tasks/         (任务定义)")
    click.echo()
    click.echo("参考现有包的结构来创建新包。")


# 在这里可以添加 package create, package check 等命令...

# --- 2. 任务管理命令组 ---
@aura.group()
def task():
    """运行和管理任务的命令组。"""
    pass


@task.command(name="run")
@click.argument('task_fqid')
@click.option('--wait', is_flag=True, help="阻塞并等待任务执行完成。")
def run_task(task_fqid: str, wait: bool):
    """运行一个临时任务 (Ad-Hoc Task)。

    通过提供任务的完全限定ID（FQID），可以直接触发任何已定义的任务，
    而无需预先在 schedule.yaml 中进行调度。

    Args:
        task_fqid (str): 任务的完全限定ID，格式为 `<plan_name>/<task_name>`。
                         例如: `my_plan/daily_check`。
        wait (bool): 如果设置，命令将阻塞直到任务执行完毕。
    """
    scheduler = get_scheduler()

    if '/' not in task_fqid:
        click.secho("错误: 任务的完全限定ID (FQID) 格式应为 'plan_name/task_name'。", fg='red')
        return

    plan_name, task_name = task_fqid.split('/', 1)

    click.echo(f"正在请求运行任务: {task_fqid}")
    result = scheduler.run_ad_hoc_task(plan_name, task_name)

    if result.get("status") == "success":
        click.secho(f"任务 '{task_fqid}' 已成功加入执行队列。", fg='green')
        if wait:
            click.echo("正在等待任务执行完成...")
            # 这是一个简化的等待逻辑，它检查任务是否不再处于运行状态。
            # 更复杂的实现可能需要一个更精密的事件通知机制。
            while scheduler.current_running_task is not None:
                # 检查是否是我们正在运行的任务
                current_item = scheduler.current_running_task
                if current_item.get('plan_name') == plan_name and current_item.get('task_name') == task_name:
                    try:
                        # 简单的等待，避免CPU空转
                        scheduler.current_running_thread.join(timeout=1)
                    except (AttributeError, TypeError):
                        # 线程可能已经结束
                        break
                else:
                    # 如果当前运行的不是我们的任务，说明我们的任务可能已经结束
                    break
            click.secho(f"任务 '{task_fqid}' 已执行完毕。", fg='green')
    else:
        click.secho(f"运行任务失败: {result.get('message')}", fg='red')


# --- 3. 服务管理命令组 ---
@aura.group()
def service():
    """查看已注册的服务的命令组。"""
    pass


@service.command(name="list")
def list_services():
    """列出所有已注册的服务及其状态。

    此命令会显示每个服务的 FQID、是否公开、当前状态（如 resolved, defined）
    以及它所属的插件。状态会用不同颜色高亮以示区分。
    """
    scheduler = get_scheduler()
    definitions = scheduler.get_all_services_status()

    if not definitions:
        click.echo("没有发现任何已注册的服务。")
        return

    click.secho(f"{'FQID':<40} {'Public':<8} {'Status':<12} {'Plugin':<30}", bold=True)
    click.echo("-" * 95)

    for s_def in definitions:
        is_public = "Yes" if s_def.get('public') else "No"
        fqid = s_def.get('fqid', 'N/A')
        status = s_def.get('status', 'N/A')

        # plugin 现在是 PluginManifest 对象，需要特殊处理
        plugin = s_def.get('plugin')
        if plugin is None:
            plugin_id = 'core'  # 核心服务
        elif hasattr(plugin, 'package'):
            plugin_id = plugin.package.canonical_id if hasattr(plugin.package, 'canonical_id') else 'N/A'
        else:
            plugin_id = 'N/A'

        # 根据状态着色
        color = 'green' if status == 'resolved' else 'yellow' if status == 'defined' else 'red'

        click.secho(f"{fqid:<40} {is_public:<8}", nl=False)
        click.secho(f"{status:<12}", fg=color, nl=False)
        click.secho(f"{plugin_id:<30}")


# --- 4. 新的插件管理命令组 ---
# 注册新的 plugin 命令组
aura.add_command(plugin_group)


if __name__ == '__main__':
    aura()
