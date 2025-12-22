---
# 核心模块: `interrupt_service.py`

## 概览
InterruptService 作为后台守护任务，定期检查中断规则，满足条件时取消任务并触发处理任务。

## 规则来源
- `plans/<plan>/interrupts.yaml`
- 格式示例：
```yaml
interrupts:
  - name: overheat_guard
    scope: global
    enabled_by_default: true
    check_interval: 5
    cooldown: 30
    condition:
      action: sensors.check_temp
      params:
        threshold: 80
    handler_task: "handle_overheat"
```

## 运行逻辑
- 读取已激活规则（全局规则 + 运行中任务的 `activates_interrupts`）
- 在对应 Plan 的 `plan_context` 下执行 `condition`
- 条件满足后：
  - 取消运行中的任务（按 `scope` 选择全局或本 Plan）
  - 以 `handler_task` 触发处理任务（source=interrupt）

## 相关字段
- `scope`: `global` 或 `plan`
- `check_interval`: 检查频率（秒）
- `cooldown`: 触发后的冷却时间（秒）
- `activates_interrupts`: 任务定义中的列表，用于激活规则
