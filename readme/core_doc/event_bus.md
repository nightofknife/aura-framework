---
# 核心模块: `event_bus.py`

## 概览
提供异步 Pub/Sub 事件总线，用于核心组件解耦通信。

## 关键对象
- `Event`: 标准事件结构（name/payload/id/timestamp/channel）
- `EventBus`: 事件订阅与发布

## 特性
- 事件名支持通配符匹配（`*`, `?`）
- 支持 `channel` 维度隔离
- 支持跨事件循环投递（`loop.call_soon_threadsafe`）
- 可持久订阅（`persistent=True`）

## 使用
- `subscribe(pattern, callback, channel="*")`
- `publish(Event(...))`
