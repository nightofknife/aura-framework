# aura_cli_interactive.py (Version 3 with Robust Startup Synchronization)

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
    """获取全局的Scheduler实例，如果不存在则创建它。"""
    global scheduler_instance
    if scheduler_instance is None:
        print("正在初始化Aura框架，加载所有定义...")
        try:
            logger.setup(log_dir='logs', task_name='aura_cli_session')
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
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header(title: str):
    print("\n" + "=" * 80)
    print(f" {title.center(78)} ")
    print("=" * 80)


def wait_for_enter():
    input("\n按回车键返回主菜单...")


# --- 功能实现 ---

def run_task(scheduler: Scheduler, ad_hoc_mode: bool):
    # ... 此函数内容不变 ...
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
    手动控制调度器的启动与停止，并健壮地处理启动同步。
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

        # 【高级方案】使用事件等待，而不是固定时间的 sleep
        print("   正在等待核心服务初始化...")

        # 等待事件被设置，最长等待15秒（超时以防万一）
        completed = scheduler.startup_complete_event.wait(timeout=15)

        if completed:
            # 【高级方案】如果成功等到事件，将 scheduler_is_running 设为 True
            scheduler_is_running = True
            print("✅ 核心服务已就绪！")
            print("✅ 调度器已在后台启动。")
            print("   它将自动执行队列中的所有任务。")
            print("   你现在可以返回主菜单添加更多任务，或随时停止调度器。")
            print("\n   👇 你将在下方看到任务的实时日志输出 👇")
        else:
            # 【高级方案】如果超时，说明后台可能出了问题。
            # 停止调度器以恢复到安全状态，并通知用户。
            print("\n⚠️ 警告：核心服务启动超时。后台可能出现严重错误。")
            print("   正在尝试自动停止调度器以进行恢复...")
            scheduler.stop_scheduler()
            scheduler_is_running = False  # 确保状态标志被重置
            print("   调度器已停止。请检查日志文件以诊断问题。")

    wait_for_enter()


def list_all_plans(scheduler: Scheduler):
    # ... 此函数内容不变 ...
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
    # ... 此函数内容不变 ...
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
    # ... 此函数内容不变 ...
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
    # ... 此函数内容不变 ...
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
