# aura_cli_interactive.py (Version 3: Manual Scheduler Control)

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

    # 【解释】导入框架核心组件。
    # 我们需要 Scheduler 来作为所有操作的入口，需要 logger 来配置日志输出。
    from packages.aura_core.scheduler import Scheduler
    from packages.aura_core.logger import logger
except ImportError as e:
    print(f"错误: 无法导入Aura核心模块。请确保你在项目根目录下运行此脚本。")
    print(f"原始错误: {e}")
    sys.exit(1)

# --- 全局状态 ---

# 【解释】这两个全局变量是这个交互式CLI的核心状态。
# - scheduler_instance: 缓存框架的主对象，避免重复初始化。
# - scheduler_is_running: 一个简单的布尔标志，用于让我们的CLI知道调度器当前是否应该在后台运行。
#   这与 Scheduler 内部的状态是解耦的，纯粹用于控制UI显示和逻辑分支。
scheduler_instance: Optional[Scheduler] = None
scheduler_is_running = False


def get_scheduler() -> Scheduler:
    """获取全局的Scheduler实例，如果不存在则创建它。"""
    global scheduler_instance
    if scheduler_instance is None:
        print("正在初始化Aura框架，加载所有定义...")
        try:
            # 【修改与解释】在初始化时就配置好日志，并允许其输出到控制台。
            # 框架行为：根据你的新设计，用户需要看到调度器运行时任务的实时日志。
            # 修改原因：因此，我们不能再像之前一样用 `console_level=None` 来禁用控制台日志。
            #            我们在这里启用它，并将日志文件存放在 'logs' 目录下，以便后续追溯。
            logger.setup(log_dir='logs', task_name='aura_cli_session')

            scheduler_instance = Scheduler()
            print("框架初始化完毕。\n")
            time.sleep(1)
        except Exception as e:
            logger.critical(f"初始化Aura框架失败: {e}", exc_info=True)
            print(f"错误: 初始化Aura框架失败，请检查日志获取详细信息。")
            sys.exit(1)
    return scheduler_instance


# --- 辅助函数 (无改动) ---
def clear_screen():
    """清空控制台屏幕。"""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header(title: str):
    """打印一个带标题的分割线。"""
    print("\n" + "=" * 80)
    print(f" {title.center(78)} ")
    print("=" * 80)


def wait_for_enter():
    """暂停程序，等待用户按回车键。"""
    input("\n按回车键返回主菜单...")


# --- 功能实现 ---

def run_task(scheduler: Scheduler, ad_hoc_mode: bool):
    """
    【重构与解释】这是一个统一的函数，用于将任务“加入队列”。
    框架行为：Scheduler的 `run_manual_task` 和 `run_ad_hoc_task` 方法被设计为非阻塞的。
              它们的作用是将一个任务请求提交给内部的 ExecutionManager 的执行队列，然后立即返回，
              并不会等待任务完成。
    修改原因：基于上述行为，此函数的核心职责被简化为：
              1. 让用户选择一个任务。
              2. 调用相应的 scheduler 方法将任务入队。
              3. 明确地告诉用户“任务已加入队列”，而不是“任务已完成”。
              它不再负责启动或停止调度器，实现了职责分离。
    """
    if ad_hoc_mode:
        all_tasks = []
        # 遍历所有方案的Orchestrator来收集任务定义
        for plan_name, orchestrator in scheduler.plan_manager.plans.items():
            for task_name in orchestrator.task_definitions.keys():
                all_tasks.append(f"{plan_name}/{task_name}")

        if not all_tasks:
            print("在所有方案中都未能找到任何任务定义。");
            wait_for_enter();
            return

        all_tasks.sort()
        task_map: Dict[int, Any] = {i + 1: fqid for i, fqid in enumerate(all_tasks)}
        header_title = "选择要运行的任意任务 (Ad-hoc)"
    else:
        schedulable_tasks = scheduler.get_schedule_status()
        if not schedulable_tasks:
            print("没有找到任何可调度的任务。请检查你的 schedule.yaml 文件。");
            wait_for_enter();
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
                print("无效的编号，请重试。");
                time.sleep(1);
                continue

            if ad_hoc_mode:
                plan_name, task_name = task_to_run.split('/', 1)
                result = scheduler.run_ad_hoc_task(plan_name, task_name)
                task_display_name = task_to_run
            else:
                task_id = task_to_run.get('id')
                result = scheduler.run_manual_task(task_id)
                task_display_name = task_to_run.get('name')

            if result.get('status') == 'success':
                print(f"\n✅ 任务 '{task_display_name}' 已成功加入待执行队列。")
                if not scheduler_is_running:
                    print("   请从主菜单启动调度器来运行它。")
            else:
                print(f"\n❌ 加入队列失败: {result.get('message')}")

            wait_for_enter()
            return
        except ValueError:
            print("无效的输入，请输入数字。");
            time.sleep(1)


def manage_scheduler_lifecycle(scheduler: Scheduler):
    """
    【新增与解释】手动控制调度器的启动与停止。
    框架行为：Scheduler 提供了 `start_scheduler()` 和 `stop_scheduler()` 两个方法来控制其生命周期。
              - `start_scheduler()`: 启动所有后台服务，如 ExecutionManager 的线程池，使其开始处理队列中的任务。
              - `stop_scheduler()`: 优雅地关闭这些服务。
    修改原因：这个函数就是这两个核心方法的UI封装。它使用全局标志 `scheduler_is_running` 来决定
              是该调用启动方法还是停止方法，并向用户提供清晰的反馈。
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
        scheduler.start_scheduler()
        scheduler_is_running = True
        print("✅ 调度器已在后台启动。")
        print("   它将自动执行队列中的所有任务。")
        print("   你现在可以返回主菜单添加更多任务，或随时停止调度器。")
        print("\n   👇 你将在下方看到任务的实时日志输出 👇")

    wait_for_enter()


# 【解释】这两个函数是只读操作，不需要修改，保持原样。
def list_all_plans(scheduler: Scheduler):
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


# ... (接上一段代码) ...

def list_all_actions(scheduler: Scheduler):
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
    """
    【修改与解释】显示主菜单，并动态展示调度器状态。
    修改原因：为了让用户清晰地知道当前调度器的状态以及下一步操作的含义，
              菜单项现在会根据全局标志 `scheduler_is_running` 动态改变。
              例如，选项 [5] 会明确地显示为“启动”或“停止”。
    """
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
    """
    【重构与解释】程序主循环。
    修改原因：主循环的逻辑根据新的设计被大大简化。
              它现在只负责显示菜单和根据用户的选择分发到对应的功能函数。
              整个程序的健壮性大大提高，因为复杂的逻辑都被封装在各自的函数里。
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
            # 【新增与解释】在退出前，确保调度器被优雅地关闭。
            # 这是一种良好的实践，可以防止任何后台线程或进程被意外遗留。
            if scheduler_is_running:
                print("程序退出前，自动停止调度器...")
                scheduler.stop_scheduler()
            print("正在退出...")
            break
        else:
            print("无效的选择，请重试。")
            time.sleep(1)


if __name__ == "__main__":
    # 【解释】程序的入口点。
    # 我们在这里直接调用 main() 函数来启动整个交互式应用。
    # 日志配置等初始化工作已移至 get_scheduler() 中，使得入口非常干净。
    main()



