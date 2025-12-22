---
# 核心模块: `logger.py`

## 概览
全局 Logger 单例，支持控制台、文件、队列和 WebSocket 等多种输出。

## 特性
- 单例模式：`logger = Logger()`
- 自定义 `TRACE` 级别（level=5）
- 文件滚动与控制台输出
- `QueueLogHandler` / `AsyncioQueueHandler` 支持 UI / WebSocket 推送

## 使用
- `logger.setup(...)` 在启动时配置输出
- 业务代码直接使用 `logger.info()` / `logger.error()` 等
