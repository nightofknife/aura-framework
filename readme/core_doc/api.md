---
# 核心模块: `api.py`

## 概览
`api.py` 提供 Action / Service / Hook 的注册入口与全局注册中心，是插件体系的核心契约。

## Action API
- `@register_action(name, read_only=False, public=False)` 注册 Action
- `@requires_services(...)` 声明服务依赖（alias 或 `alias=service_fqid`）
- `ACTION_REGISTRY` 保存 `ActionDefinition`（包含 `fqid`, `public`, `is_async` 等元数据）

## Service API
- `@register_service(alias, public=False)` 注册服务
- `ServiceRegistry` 管理服务生命周期与依赖注入（单例、懒加载、循环检测）
- 支持服务扩展与覆盖：
  - `plugin.yaml` 中 `extends` 声明扩展：`{service, from}`
  - `plugin.yaml` 中 `overrides` 声明覆盖：`author/name/alias`
- 扩展服务通过 `InheritanceProxy` 组合父子实例
- 核心服务可用 `service_registry.register_instance` 直接注册实例

## Hook API
- `@register_hook(name)` 注册 Hook
- `HookManager.trigger(name, **payload)` 触发所有监听器（支持 sync/async）
- `ExecutionManager` 在任务生命周期中触发：
  `before_task_run` / `after_task_success` / `after_task_failure` / `after_task_run`

## 与其他模块的关系
- `PluginManager` 在加载 `api.yaml` 时写入注册中心
- `ActionInjector` / `ExecutionEngine` 在运行期查询 Action 与 Service
