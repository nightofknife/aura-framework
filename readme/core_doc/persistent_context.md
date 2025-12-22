---
# 核心模块: `persistent_context.py`

## 概览
`PersistentContext` 提供异步、线程安全的 JSON 持久化上下文存储。

## 主要特性
- `create()` 异步初始化并加载数据
- `load()` / `save()` 均通过线程池执行 I/O
- 内置 `asyncio.Lock` 保护并发
