---
# 核心模块: `config_loader.py`

## 概览
`config_loader.py` 提供全局配置读取入口，封装了 `ConfigService` 的加载与缓存。

## 配置来源与优先级
1. 环境变量（`AURA_` 前缀）
2. 根目录 `config.yaml`
3. Plan 专属 `plans/<plan>/config.yaml`

Plan 级配置需要配合 `plan_context` 使用（或由 Orchestrator 自动设置），从而按 Plan 隔离读取。

## API
- `get_config_value(key_path, default=None, base_path=None)`
  - 使用点号路径读取值，例如 `scheduler.num_event_workers`
- `get_config_section(section, default=None, base_path=None)`
  - 读取一个配置段并确保返回 dict

## 环境变量映射
- 以 `AURA_` 开头的环境变量会映射为点号路径：
  - `AURA_SCHEDULER_NUM_EVENT_WORKERS=2` -> `scheduler.num_event_workers = 2`

## 示例
```python
from packages.aura_core.config_loader import get_config_value

workers = get_config_value("scheduler.num_event_workers", 1)
```

## 注意
- `ConfigService` 会在启动时加载 `.env`（若安装 `python-dotenv`）。
- Plan 配置由 `Scheduler` 在加载 Plan 时注册。
