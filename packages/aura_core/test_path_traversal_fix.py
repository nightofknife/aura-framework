# -*- coding: utf-8 -*-
"""
安全测试：验证路径穿越漏洞修复

此测试文件验证 aura.run_task 的安全加固是否生效。
运行方式：python -m pytest packages/aura_core/test_path_traversal_fix.py
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from packages.aura_core.action_injector import ActionInjector
from packages.aura_core.context import ExecutionContext


class TestPathTraversalProtection:
    """测试路径穿越攻击防护"""

    @pytest.fixture
    def mock_components(self):
        """创建模拟组件"""
        # 模拟 ExecutionContext
        context = ExecutionContext()

        # 模拟 ExecutionEngine
        engine = MagicMock()
        engine.orchestrator = MagicMock()
        engine.orchestrator.plan_name = "test_plan"

        # 模拟 TemplateRenderer
        renderer = AsyncMock()

        # 模拟 services
        services = {}

        # 创建 ActionInjector 实例
        injector = ActionInjector(context, engine, renderer, services)

        return injector, renderer

    @pytest.mark.asyncio
    async def test_block_parent_directory_traversal(self, mock_components):
        """测试：阻止 ../ 路径穿越"""
        injector, renderer = mock_components

        # 模拟渲染器返回恶意任务名
        renderer.get_render_scope.return_value = {}
        renderer.render.return_value = {
            'task_name': '../../../other_plan/secret_task',
            'inputs': {}
        }

        # 应该抛出 ValueError
        with pytest.raises(ValueError, match="path traversal sequence"):
            await injector._execute_run_task({'task_name': '{{malicious}}'})

    @pytest.mark.asyncio
    async def test_block_double_dot_in_middle(self, mock_components):
        """测试：阻止中间包含 .. 的路径"""
        injector, renderer = mock_components

        renderer.get_render_scope.return_value = {}
        renderer.render.return_value = {
            'task_name': 'some/../other/task',
            'inputs': {}
        }

        with pytest.raises(ValueError, match="path traversal sequence"):
            await injector._execute_run_task({'task_name': 'some/../other/task'})

    @pytest.mark.asyncio
    async def test_block_absolute_path_unix(self, mock_components):
        """测试：阻止 Unix 绝对路径"""
        injector, renderer = mock_components

        renderer.get_render_scope.return_value = {}
        renderer.render.return_value = {
            'task_name': '/etc/passwd/task',
            'inputs': {}
        }

        with pytest.raises(ValueError, match="cannot be an absolute path"):
            await injector._execute_run_task({'task_name': '/etc/passwd/task'})

    @pytest.mark.asyncio
    async def test_block_absolute_path_windows(self, mock_components):
        """测试：阻止 Windows 绝对路径"""
        injector, renderer = mock_components

        renderer.get_render_scope.return_value = {}
        renderer.render.return_value = {
            'task_name': '\\Windows\\System32\\task',
            'inputs': {}
        }

        with pytest.raises(ValueError, match="cannot be an absolute path"):
            await injector._execute_run_task({'task_name': '\\Windows\\System32\\task'})

    @pytest.mark.asyncio
    async def test_block_cross_plan_access(self, mock_components):
        """测试：阻止跨 Plan 访问"""
        injector, renderer = mock_components

        renderer.get_render_scope.return_value = {}
        renderer.render.return_value = {
            'task_name': 'other_plan/task_name',
            'inputs': {}
        }

        with pytest.raises(ValueError, match="Cross-plan task access is forbidden"):
            await injector._execute_run_task({'task_name': 'other_plan/task_name'})

    @pytest.mark.asyncio
    async def test_block_non_string_task_name(self, mock_components):
        """测试：阻止非字符串类型的任务名"""
        injector, renderer = mock_components

        renderer.get_render_scope.return_value = {}

        # 测试整数
        renderer.render.return_value = {'task_name': 12345, 'inputs': {}}
        with pytest.raises(ValueError, match="must be a string"):
            await injector._execute_run_task({'task_name': 12345})

        # 测试列表
        renderer.render.return_value = {'task_name': ['task'], 'inputs': {}}
        with pytest.raises(ValueError, match="must be a string"):
            await injector._execute_run_task({'task_name': ['task']})

    @pytest.mark.asyncio
    async def test_allow_valid_task_name(self, mock_components):
        """测试：允许合法的任务名"""
        injector, renderer = mock_components

        # 模拟成功的任务执行
        renderer.get_render_scope.return_value = {}
        renderer.render.return_value = {
            'task_name': 'valid_task_name',
            'inputs': {'param': 'value'}
        }

        # 模拟 orchestrator.execute_task 返回成功结果
        injector.engine.orchestrator.execute_task = AsyncMock(return_value={
            'status': 'SUCCESS',
            'framework_data': {'nodes': {}}
        })

        # 应该成功执行
        result = await injector._execute_run_task({'task_name': 'valid_task_name'})

        # 验证调用
        injector.engine.orchestrator.execute_task.assert_called_once()
        assert result == {'nodes': {}}

    @pytest.mark.asyncio
    async def test_allow_subdirectory_task_within_plan(self, mock_components):
        """测试：允许 Plan 内子目录的任务（使用反斜杠路径）"""
        injector, renderer = mock_components

        renderer.get_render_scope.return_value = {}

        # 注意：当前实现会阻止任何包含 / 的路径
        # 如果需要支持子目录，需要修改验证逻辑
        # 这个测试验证当前的严格行为
        renderer.render.return_value = {
            'task_name': 'subdir/task',
            'inputs': {}
        }

        # 当前实现会阻止这种情况（出于安全考虑）
        with pytest.raises(ValueError, match="Cross-plan task access is forbidden"):
            await injector._execute_run_task({'task_name': 'subdir/task'})


class TestEdgeCases:
    """测试边界情况"""

    @pytest.fixture
    def mock_components(self):
        context = ExecutionContext()
        engine = MagicMock()
        engine.orchestrator = MagicMock()
        engine.orchestrator.plan_name = "test_plan"
        renderer = AsyncMock()
        services = {}
        injector = ActionInjector(context, engine, renderer, services)
        return injector, renderer

    @pytest.mark.asyncio
    async def test_empty_task_name(self, mock_components):
        """测试：空任务名"""
        injector, renderer = mock_components

        renderer.get_render_scope.return_value = {}
        renderer.render.return_value = {'task_name': '', 'inputs': {}}

        with pytest.raises(ValueError, match="requires a 'task_name' parameter"):
            await injector._execute_run_task({'task_name': ''})

    @pytest.mark.asyncio
    async def test_none_task_name(self, mock_components):
        """测试：None 任务名"""
        injector, renderer = mock_components

        renderer.get_render_scope.return_value = {}
        renderer.render.return_value = {'task_name': None, 'inputs': {}}

        with pytest.raises(ValueError, match="requires a 'task_name' parameter"):
            await injector._execute_run_task({'task_name': None})

    @pytest.mark.asyncio
    async def test_whitespace_only_task_name(self, mock_components):
        """测试：仅包含空白字符的任务名"""
        injector, renderer = mock_components

        renderer.get_render_scope.return_value = {}
        renderer.render.return_value = {'task_name': '   ', 'inputs': {}}

        # 空白字符会通过基本验证，但会被 Orchestrator 拒绝
        injector.engine.orchestrator.execute_task = AsyncMock(
            side_effect=ValueError("Task not found")
        )

        with pytest.raises(ValueError):
            await injector._execute_run_task({'task_name': '   '})


if __name__ == '__main__':
    # 运行测试
    pytest.main([__file__, '-v', '--tb=short'])
