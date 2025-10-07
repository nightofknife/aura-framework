"""
Aura 框架的命令行接口（CLI）。

该脚本使用 `click` 库构建，为用户提供了一套通过命令行与 Aura 框架
进行交互的工具。它允许用户在不启动完整图形界面的情况下，执行关键的
开发和管理任务。

主要功能通过命令组（`@click.group()`）来组织：
- **`package`**: 用于管理 Aura 包（插件），例如，强制从源码重新构建
  一个包的 `api.yaml` 清单文件。
- **`task`**: 用于运行和管理任务，例如，以“临时”（ad-hoc）模式运行
  任何已定义的任务。
- **`service`**: 用于检查和管理核心服务，例如，列出所有已注册的服务
  及其当前状态。

在执行任何命令之前，脚本会确保全局的 `Scheduler` 实例被初始化，
从而加载整个框架，使其处于可用状态。

使用示例:
    # 列出所有已注册的服务
    python cli.py service list

    # 运行一个指定的任务
    python cli.py task run my_plan/my_task

    # 强制重新构建一个包
    python cli.py package build ./packages/my_package
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
    from packages.aura_core.builder import build_package_from_source, API_FILE_NAME
    from packages.aura_core.logger import logger
except ImportError as e:
    print(f"错误: 无法导入Aura核心模块。请确保你在项目根目录下运行此脚本，并且所有依赖都已安装。")
    print(f"原始错误: {e}")
    sys.exit(1)

# --- 全局框架实例 ---
# 在CLI脚本的生命周期内，我们只实例化一次Scheduler，以便所有命令共享同一个加载好的框架状态。
scheduler_instance: Scheduler = None


def get_scheduler():
    """获取全局的Scheduler实例，如果不存在则创建它。"""
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
    """Aura 3.0 自动化框架命令行工具。"""
    # 这个函数是所有命令的入口，我们在这里确保框架被加载。
    get_scheduler()
    pass


# --- 1. 包管理命令组 ---
@aura.group()
def package():
    """管理Aura包（插件）。"""
    pass


@package.command()
@click.argument('package_path', type=click.Path(exists=True, file_okay=False, resolve_path=True))
def build(package_path: str):
    """
    强制从源码构建一个包，并生成/更新其 api.yaml 文件。
    """
    scheduler = get_scheduler()
    package_path_obj = Path(package_path)

    # 从已加载的插件注册表中找到对应的PluginDefinition
    plugin_def = None
    for p_def in scheduler.plugin_registry.values():
        if p_def.path == package_path_obj:
            plugin_def = p_def
            break

    if not plugin_def:
        click.secho(f"错误: 路径 '{package_path}' 不是一个已注册的Aura包。", fg='red')
        return

    click.echo(f"正在为包 '{plugin_def.canonical_id}' 从源码强制构建...")
    try:
        # 删除旧的api.yaml以确保重新生成
        api_file = package_path_obj / API_FILE_NAME
        if api_file.exists():
            api_file.unlink()
            click.echo(f"  - 已删除旧的 {API_FILE_NAME}")

        build_package_from_source(plugin_def)
        click.secho(f"成功！包 '{plugin_def.canonical_id}' 已构建，{API_FILE_NAME} 已更新。", fg='green')
    except Exception as e:
        logger.error(f"构建包 '{plugin_def.canonical_id}' 失败: {e}", exc_info=True)
        click.secho(f"构建失败，请检查日志。", fg='red')


# 在这里可以添加 package create, package check 等命令...

# --- 2. 任务管理命令组 ---
@aura.group()
def task():
    """运行和管理任务。"""
    pass


@task.command(name="run")
@click.argument('task_fqid')
@click.option('--wait', is_flag=True, help="阻塞并等待任务执行完成。")
def run_task(task_fqid: str, wait: bool):
    """
    运行一个临时任务 (Ad-Hoc Task)。
    TASK_FQID 的格式为: <plan_name>/<task_name>
    例如: my_plan/daily_check
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
    """查看已注册的服务。"""
    pass


@service.command(name="list")
def list_services():
    """列出所有已注册的服务及其状态。"""
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
        plugin_id = s_def.get('plugin', {}).get('canonical_id', 'N/A')

        # 根据状态着色
        color = 'green' if status == 'resolved' else 'yellow' if status == 'defined' else 'red'

        click.secho(f"{fqid:<40} {is_public:<8}", nl=False)
        click.secho(f"{status:<12}", fg=color, nl=False)
        click.secho(f"{plugin_id:<30}")


if __name__ == '__main__':
    aura()