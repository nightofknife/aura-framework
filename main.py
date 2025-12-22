# -*- coding: utf-8 -*-
"""Aura 框架的交互式命令行界面 (CLI)。

该脚本提供了一个用户友好的菜单，用于与 Aura 调度器进行交互，
包括启动/停止调度器、将任务添加到队列、以及查看已加载的插件信息。
它作为 Aura 框架的主要用户入口点。

主要功能:
- 初始化并获取全局唯一的调度器实例。
- 提供清晰的命令行菜单，展示可用操作。
- 支持将预定任务和临时任务（Ad-hoc）添加到执行队列。
- 管理调度器的生命周期（启动和停止）。
- 实时显示调度器状态。
- 优雅地处理启动同步和程序退出。
"""
import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

# --- 核心初始化 ---
try:
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from packages.aura_core.scheduler import Scheduler
    from packages.aura_core.logger import logger
except ImportError as e:
    print(f"错误: 无法导入Aura核心模块。请确保你在项目根目录下运行此脚本。")
    print(f"原始错误: {e}")
    sys.exit(1)

# --- 全局状态 ---
scheduler_instance: Optional[Scheduler] = None
scheduler_is_running = False


def get_scheduler() -> Scheduler:
    """获取全局的Scheduler实例，如果不存在则进行初始化。

    这是一个单例模式的实现，确保整个应用只使用一个调度器实例。
    首次调用时，它会执行必要的初始化步骤，包括设置日志和创建Scheduler对象。

    Returns:
        Scheduler: 全局唯一的调度器实例。

    Raises:
        SystemExit: 如果初始化过程中发生严重错误，则会终止程序。
    """
    global scheduler_instance
    if scheduler_instance is None:
        print("正在初始化Aura框架，加载所有定义...")
        try:
            from packages.aura_core.config_loader import get_config_value
            logger.setup(
                log_dir=str(get_config_value("logging.log_dir", "logs")),
                task_name=str(get_config_value("logging.task_name.cli", "aura_cli_session")),
            )
            scheduler_instance = Scheduler()
            print("框架初始化完毕。\n")
            time.sleep(1)
        except Exception as e:
            logger.critical(f"初始化Aura框架失败: {e}", exc_info=True)
            print(f"错误: 初始化Aura框架失败，请检查日志获取详细信息。")
            sys.exit(1)
    return scheduler_instance


# --- 辅助函数 ---
def clear_screen():
    """清空控制台屏幕。"""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header(title: str):
    """打印一个带标题的格式化头部。

    Args:
        title: 要在头部中央显示的标题字符串。
    """
    print("\n" + "=" * 80)
    print(f" {title.center(78)} ")
    print("=" * 80)


def wait_for_enter():
    """暂停程序执行，等待用户按下回车键。"""
    input("\n按回车键返回主菜单...")


# --- 功能实现 ---

def run_task(scheduler: Scheduler, ad_hoc_mode: bool):
    """显示任务列表并处理用户选择，以将任务加入队列。

    根据 `ad_hoc_mode` 的值，此函数可以显示可调度的任务列表
    或所有方案中定义的全部任务列表。用户选择一个任务后，
    可以指定运行次数，然后批量添加到调度器的执行队列中。

    Args:
        scheduler: 当前的 Scheduler 实例。
        ad_hoc_mode: 如果为 True，则显示所有可用任务（临时模式）；
                     如果为 False，则仅显示在 schedule.yaml 中定义的任务。
    """
    if ad_hoc_mode:
        all_tasks = []
        # 遍历所有方案的Orchestrator来收集任务定义
        for plan_name, orchestrator in scheduler.plan_manager.plans.items():
            for task_name in orchestrator.task_definitions.keys():
                all_tasks.append(f"{plan_name}/{task_name}")

        if not all_tasks:
            print("在所有方案中都未能找到任何任务定义。")
            wait_for_enter()
            return

        all_tasks.sort()
        task_map: Dict[int, Any] = {i + 1: fqid for i, fqid in enumerate(all_tasks)}
        header_title = "选择要运行的任意任务 (Ad-hoc)"
    else:
        schedulable_tasks = scheduler.get_schedule_status()
        if not schedulable_tasks:
            print("没有找到任何可调度的任务。请检查你的 schedule.yaml 文件。")
            wait_for_enter()
            return
        task_map = {i + 1: task for i, task in enumerate(schedulable_tasks)}
        header_title = "选择要运行的可调度任务"

    while True:
        clear_screen()
        print_header(header_title)

        if ad_hoc_mode:
            for i, fqid in task_map.items():
                print(f"  [{i:2d}] {fqid}")
        else:
            for i, task in task_map.items():
                print(f"  [{i:2d}] {task.get('name', '未命名'):<40} (Plan: {task.get('plan_name')})")

        print("\n  [b] 返回主菜单")
        choice = input("\n请输入任务编号: ").strip().lower()

        if choice == 'b': return

        try:
            choice_num = int(choice)
            task_to_run = task_map.get(choice_num)
            if not task_to_run:
                print("无效的编号，请重试。")
                time.sleep(1)
                continue

            # ✅ 新增：询问运行次数
            while True:
                try:
                    run_count_input = input("\n请输入运行次数 (默认为1): ").strip()
                    if not run_count_input:
                        run_count = 1
                    else:
                        run_count = int(run_count_input)
                        if run_count <= 0:
                            print("运行次数必须大于0，请重新输入。")
                            continue
                    break
                except ValueError:
                    print("无效的输入，请输入一个正整数。")

            # ✅ 批量添加任务
            print(f"\n正在添加 {run_count} 个任务到队列...")
            success_count = 0
            failed_count = 0

            if ad_hoc_mode:
                plan_name, task_name = task_to_run.split('/', 1)
                task_display_name = task_to_run
            else:
                task_id = task_to_run.get('id')
                task_display_name = task_to_run.get('name')

            for i in range(1, run_count + 1):
                try:
                    if ad_hoc_mode:
                        result = scheduler.run_ad_hoc_task(plan_name, task_name)
                    else:
                        result = scheduler.run_manual_task(task_id)

                    if result.get('status') == 'success':
                        success_count += 1
                        print(f"  [{i}/{run_count}] ✅ 任务已入队 (cid: {result.get('cid', 'N/A')})")
                    else:
                        failed_count += 1
                        print(f"  [{i}/{run_count}] ❌ 失败: {result.get('message')}")

                    # 短暂延迟以避免过快的并发请求
                    if i < run_count:
                        time.sleep(0.05)

                except Exception as e:
                    failed_count += 1
                    print(f"  [{i}/{run_count}] ❌ 异常: {e}")

            # 显示汇总结果
            print(f"\n{'=' * 60}")
            print(f"任务添加完成:")
            print(f"  ✅ 成功: {success_count}/{run_count}")
            if failed_count > 0:
                print(f"  ❌ 失败: {failed_count}/{run_count}")
            print(f"{'=' * 60}")

            if success_count > 0 and not scheduler_is_running:
                print("\n💡 提示: 请从主菜单启动调度器来运行这些任务。")

            wait_for_enter()
            return

        except ValueError:
            print("无效的输入，请输入数字。")
            time.sleep(1)


def manage_scheduler_lifecycle(scheduler: Scheduler):
    """手动控制调度器的启动与停止，并健壮地处理启动同步。

    如果调度器当前正在运行，则调用此函数会停止它。
    如果调度器已停止，则会启动它，并等待其内部服务完全初始化。
    这里使用了一个事件（`startup_complete_event`）来确保在宣布启动成功前，
    所有后台服务都已准备就绪，避免了使用不可靠的固定时间延迟。

    Args:
        scheduler: 当前的 Scheduler 实例。
    """
    global scheduler_is_running

    clear_screen()
    if scheduler_is_running:
        print("正在停止调度器...")
        scheduler.stop_scheduler()
        scheduler_is_running = False
        print("✅ 调度器已停止。所有后台任务已结束。")
    else:
        print("正在启动调度器...")
        scheduler.start_scheduler()  # 后台线程在这里启动

        # 使用事件等待，而不是固定时间的 sleep
        print("   正在等待核心服务初始化...")

        # 等待事件被设置，最长等待15秒（超时以防万一）
        completed = scheduler.startup_complete_event.wait(timeout=15)

        if completed:
            scheduler_is_running = True
            print("✅ 核心服务已就绪！")
            print("✅ 调度器已在后台启动。")
            print("   它将自动执行队列中的所有任务。")
            print("   你现在可以返回主菜单添加更多任务，或随时停止调度器。")
            print("\n   👇 你将在下方看到任务的实时日志输出 👇")
        else:
            # 如果超时，说明后台可能出了问题。
            print("\n⚠️ 警告：核心服务启动超时。后台可能出现严重错误。")
            print("   正在尝试自动停止调度器以进行恢复...")
            scheduler.stop_scheduler()
            scheduler_is_running = False  # 确保状态标志被重置
            print("   调度器已停止。请检查日志文件以诊断问题。")

    wait_for_enter()


def list_all_plans(scheduler: Scheduler):
    """显示所有已从插件目录加载的方案（Plans）的列表。

    Args:
        scheduler: 当前的 Scheduler 实例。
    """
    clear_screen()
    print_header("所有已加载的方案 (Plans)")
    registry = scheduler.plan_manager.plugin_manager.plugin_registry
    plan_defs = [p for p in registry.values() if p.plugin_type == 'plan']
    if not plan_defs:
        print("没有找到任何方案。")
    else:
        print(f"{'规范ID':<40} {'版本':<10} {'路径'}")
        print("-" * 80)
        for p_def in sorted(plan_defs, key=lambda p: p.canonical_id):
            print(f"{p_def.canonical_id:<40} {p_def.version:<10} {p_def.path}")
    wait_for_enter()


def list_all_actions(scheduler: Scheduler):
    """显示所有已注册的动作（Actions）的列表。

    Args:
        scheduler: 当前的 Scheduler 实例。
    """
    clear_screen()
    print_header("所有已注册的动作 (Actions)")
    action_defs = scheduler.actions.get_all_action_definitions()
    if not action_defs:
        print("没有找到任何动作。")
    else:
        print(f"{'动作 FQID':<50} {'来源插件'}")
        print("-" * 80)
        for a_def in sorted(action_defs, key=lambda a: a.fqid):
            plugin_id = a_def.plugin.canonical_id if a_def.plugin else "N/A"
            print(f"{a_def.fqid:<50} {plugin_id}")
    wait_for_enter()


def display_menu():
    """显示主菜单，并根据调度器的当前状态动态调整选项。"""
    global scheduler_is_running

    print_header("Aura 交互式控制台")
    status_text = "运行中 (正在执行任务...)" if scheduler_is_running else "已停止"
    print(f"  调度器状态: {status_text}")
    print("-" * 80)
    print("  [1] 添加一个可调度任务到队列")
    print("  [2] 添加一个任意任务到队列 (Ad-hoc)")
    print("\n  [3] 列出所有已加载的方案")
    print("  [4] 列出所有已注册的动作")

    if scheduler_is_running:
        print("\n  [5] 停止调度器")
    else:
        print("\n  [5] 启动调度器 (开始执行队列任务)")

    print("\n  [6] 退出")


def main():
    """程序主入口函数。

    负责初始化调度器并运行主事件循环，处理用户输入并分派到相应的功能函数。
    在退出前会确保调度器被安全地停止。
    """
    scheduler = get_scheduler()

    while True:
        clear_screen()
        display_menu()
        choice = input("\n请输入你的选择: ").strip()

        if choice == '1':
            run_task(scheduler, ad_hoc_mode=False)
        elif choice == '2':
            run_task(scheduler, ad_hoc_mode=True)
        elif choice == '3':
            list_all_plans(scheduler)
        elif choice == '4':
            list_all_actions(scheduler)
        elif choice == '5':
            manage_scheduler_lifecycle(scheduler)
        elif choice == '6':
            if scheduler_is_running:
                print("程序退出前，自动停止调度器...")
                scheduler.stop_scheduler()
            print("正在退出...")
            break
        else:
            print("无效的选择，请重试。")
            time.sleep(1)


if __name__ == "__main__":
    main()
