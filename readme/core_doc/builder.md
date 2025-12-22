---
# 核心模块: `builder.py`

## 概览
从插件源码生成 `api.yaml`，用于插件的快速加载与无源码分发。

## 生成内容
- `exports.services`: `@register_service` 且 `public=True` 的服务
- `exports.actions`: `@register_action` 且 `public=True` 的 Action
- `entry_points.tasks`: `meta.entry_point: true` 的任务入口

## 任务入口识别
- 支持单任务 YAML 与多任务 YAML 两种写法
- 入口信息来自 `meta.title` / `meta.description` / `meta.icon`

## 何时执行
- `PluginManager` 在 `api.yaml` 缺失时自动构建
- CLI: `python cli.py package build <package_path>`
