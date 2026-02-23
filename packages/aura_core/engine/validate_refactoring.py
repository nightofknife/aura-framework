# -*- coding: utf-8 -*-
"""Engine模块重构验证脚本

验证重构后的Engine模块：
1. 导入检查
2. 类实例化检查
3. 子组件创建检查
4. API兼容性检查
"""
import sys
import traceback


def test_imports():
    """测试所有模块导入"""
    print("1. 测试模块导入...")

    try:
        # 测试外观模式导入
        from packages.aura_core.engine import ExecutionEngine, StepState
        print("   ✅ 外观模式导入成功: ExecutionEngine, StepState")

        # 测试子模块导入
        from packages.aura_core.engine.graph_builder import GraphBuilder
        print("   ✅ GraphBuilder 导入成功")

        from packages.aura_core.engine.dag_scheduler import DAGScheduler
        print("   ✅ DAGScheduler 导入成功")

        from packages.aura_core.engine.node_executor import NodeExecutor
        print("   ✅ NodeExecutor 导入成功")


        from packages.aura_core.engine.execution_engine import ExecutionEngine as EE
        print("   ✅ ExecutionEngine (直接导入) 成功")

        return True
    except Exception as e:
        print(f"   ❌ 导入失败: {e}")
        traceback.print_exc()
        return False


def test_class_structure():
    """测试类结构"""
    print("\n2. 测试类结构...")

    try:
        from packages.aura_core.engine import ExecutionEngine, StepState

        # 检查StepState枚举
        assert hasattr(StepState, 'PENDING')
        assert hasattr(StepState, 'RUNNING')
        assert hasattr(StepState, 'SUCCESS')
        assert hasattr(StepState, 'FAILED')
        assert hasattr(StepState, 'SKIPPED')
        print("   ✅ StepState 枚举包含所有状态")

        # 检查ExecutionEngine类属性
        assert hasattr(ExecutionEngine, '__init__')
        assert hasattr(ExecutionEngine, 'run')
        assert hasattr(ExecutionEngine, '_check_pause')
        assert hasattr(ExecutionEngine, '_prepare_node_context')
        assert hasattr(ExecutionEngine, '_on_task_completed')
        assert hasattr(ExecutionEngine, '_create_run_state')
        print("   ✅ ExecutionEngine 包含所有必要方法")

        return True
    except Exception as e:
        print(f"   ❌ 类结构检查失败: {e}")
        traceback.print_exc()
        return False


def test_component_creation():
    """测试子组件创建"""
    print("\n3. 测试子组件创建...")

    try:
        from packages.aura_core.engine import ExecutionEngine
        import asyncio

        # 创建模拟的orchestrator和pause_event
        class MockOrchestrator:
            def __init__(self):
                self.debug_mode = True
                self.services = {'state_store': None}

        orchestrator = MockOrchestrator()
        pause_event = asyncio.Event()
        pause_event.set()  # 默认不暂停

        # 创建ExecutionEngine实例
        engine = ExecutionEngine(orchestrator, pause_event)
        print("   ✅ ExecutionEngine 实例创建成功")

        # 检查子组件是否创建
        assert hasattr(engine, 'graph_builder')
        assert engine.graph_builder is not None
        print("   ✅ GraphBuilder 组件已创建")

        assert hasattr(engine, 'dag_scheduler')
        assert engine.dag_scheduler is not None
        print("   ✅ DAGScheduler 组件已创建")

        assert hasattr(engine, 'node_executor')
        assert engine.node_executor is not None
        print("   ✅ NodeExecutor 组件已创建")


        # 检查子组件的engine引用
        assert engine.graph_builder.engine is engine
        assert engine.dag_scheduler.engine is engine
        assert engine.node_executor.engine is engine
        print("   ✅ 所有子组件正确引用父引擎")

        return True
    except Exception as e:
        print(f"   ❌ 组件创建失败: {e}")
        traceback.print_exc()
        return False


def test_api_compatibility():
    """测试API兼容性"""
    print("\n4. 测试API兼容性...")

    try:
        from packages.aura_core.engine import ExecutionEngine
        import asyncio

        class MockOrchestrator:
            def __init__(self):
                self.debug_mode = True
                self.services = {'state_store': None}

        orchestrator = MockOrchestrator()
        pause_event = asyncio.Event()
        pause_event.set()

        engine = ExecutionEngine(orchestrator, pause_event)

        # 检查核心状态属性
        assert hasattr(engine, 'nodes')
        assert hasattr(engine, 'dependencies')
        assert hasattr(engine, 'reverse_dependencies')
        assert hasattr(engine, 'step_states')
        assert hasattr(engine, 'ready_queue')
        assert hasattr(engine, 'root_context')
        assert hasattr(engine, 'node_contexts')
        assert hasattr(engine, 'running_tasks')
        print("   ✅ 所有核心状态属性存在")


        # 检查节点元数据属性
        assert hasattr(engine, 'node_metadata')
        print("   ✅ 节点元数据属性存在")

        # 检查方法签名（通过inspect）
        import inspect

        # run方法签名
        run_sig = inspect.signature(engine.run)
        params = list(run_sig.parameters.keys())
        assert 'task_data' in params
        assert 'task_name' in params
        assert 'root_context' in params
        print("   ✅ run() 方法签名正确")

        return True
    except Exception as e:
        print(f"   ❌ API兼容性检查失败: {e}")
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("=" * 60)
    print("Engine 模块重构验证")
    print("=" * 60)

    results = []

    # 运行所有测试
    results.append(("导入检查", test_imports()))
    results.append(("类结构检查", test_class_structure()))
    results.append(("组件创建检查", test_component_creation()))
    results.append(("API兼容性检查", test_api_compatibility()))

    # 输出总结
    print("\n" + "=" * 60)
    print("验证总结")
    print("=" * 60)

    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{name}: {status}")

    all_passed = all(result[1] for result in results)

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有验证通过！Engine模块重构成功！")
        print("=" * 60)
        return 0
    else:
        print("⚠️  部分验证失败，请检查错误信息")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
