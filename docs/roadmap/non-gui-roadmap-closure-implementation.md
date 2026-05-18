# Aura 非 GUI Roadmap Closure 实施说明

本轮只补齐 `aura-framework-upgrade-roadmap.md` 中非 GUI 的剩余闭环，不扩展 GUI，不引入远程 marketplace，不引入 Docker/Poetry/pyproject，也不恢复或迁移已清理业务资产。

## 已收口能力

- `framework-core` smoke 继续纳入 release gate，并增强 import boundary 输出。core smoke 期间禁止加载 `plans.aura_base`、OpenCV、PaddleOCR、pywin32、ultralytics 等 desktop-only 模块。
- `ScreenService` 保持原同步 API，但内部统一通过 `DesktopFacade` 调用 capture/window backend，不再在 service 层直接导入 Win32/ctypes。
- `DesktopFacade` 接入真实 adapter：`gdi`、`mss`、`dxgi`、`printwindow`、`win32`、`paddleocr`、`win32_postmessage`，不可用 backend 返回结构化失败。
- action envelope 会把旧 `MatchResult/OcrResult` 适配成标准 locator 诊断数据，原 action 返回值仍保留在 `data.value`。
- package upgrade `--apply` 增加 fake fixture gate、文件/lock/workspace 备份、runtime reload plan/apply gate 和失败 rollback。
- package migration hook 默认 dry-run，真实执行必须传 `--execute --trusted`，且受当前 policy profile 限制。
- 新增 persistence lifecycle CLI：status、cleanup、archive、export。默认只清理可重建运维数据，不删除 run/evidence 原始引用。
- compatibility governance 增加 deprecation 检查，过期 deprecation 必须有 migration note。
- fake fixture 仍进入默认 release gate；真实 desktop/raw/hid/yolo fixture 作为显式 opt-in，不进入默认验收。

## 新增命令

```powershell
python cli.py persistence status
python cli.py persistence cleanup --older-than 30 --dry-run
python cli.py persistence archive --older-than 90 --output diagnostics/archive.zip
python cli.py persistence export --format jsonl --output diagnostics/runs.jsonl

python cli.py compat deprecations

python cli.py package migrations PACKAGE_ID
python cli.py package migrations PACKAGE_ID --execute --trusted

python cli.py fixture list --include-real
python cli.py fixture run real/capture --allow-side-effects
```

## 验收边界

默认 release gate 不触发真实截图、键鼠、OCR、YOLO、raw input 或 HID 输入。真实自动化验证必须通过显式 fixture 命令和 pytest marker opt-in 执行。
