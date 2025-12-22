---
# 核心模块: `action_injector.py`

## 概览
ActionInjector 负责执行单个 Action：渲染参数、注入服务与上下文、验证模型，并在 sync/async 间选择合适的执行方式。

## 关键职责
- 从 `ACTION_REGISTRY` 获取 `ActionDefinition`
- 使用 `TemplateRenderer` 渲染 `params`（作用域: `state` / `initial` / `inputs` / `loop` / `nodes`）
- 按 `@requires_services` 注入服务，支持 `ExecutionContext` 与 `ExecutionEngine` 注入
- 若 Action 接收 Pydantic `BaseModel`，自动完成校验与实例化
- 处理内建 Action `aura.run_task`（子任务调用）

## 调用流程
1. 渲染参数 -> `rendered_params`
2. 构造调用参数（注入 service / context / engine）
3. `async def` 直接 `await`，同步函数放入线程池
4. 返回 Action 结果（或子任务 `framework_data`）

## 内建 `aura.run_task`
- 参数: `task_name` (必填), `inputs` (可选 dict)
- 行为: 通过当前 Plan 的 Orchestrator 执行子任务
- 返回: 子任务的 `framework_data`（便于读取 `nodes`、`inputs` 等）

## 说明
- 模板渲染不提供 `config()` helper；如需配置，请在 Action/Service 内通过 `ConfigService` 获取。
- 注入规则以参数名为主：`context` / `engine` 为保留注入点，其余来自 `params` 或默认值。
