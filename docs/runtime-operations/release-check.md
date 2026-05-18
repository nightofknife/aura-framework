# Release Check

`release check` 是本地 release readiness 门禁，不上传、不发布、不修改远程状态。

## Command

```powershell
python cli.py release check
```

默认执行：

- `core smoke --profile framework-core --minimal-workspace`
- `validate --strict`
- `package doctor`
- `policy doctor`
- `compat check`
- `fixture verify-all`
- stable API and contract snapshot check
- SQLite migration status
- `pytest -m "not slow and not yolo"`
- `npm run build`

## Fast Local Loop

开发中可以跳过耗时项：

```powershell
python cli.py release check --skip-tests --skip-gui-build
```

最终合并或发布前应运行完整检查。

## Failure Handling

任一子检查失败时，`release check` 返回非零码，并在 JSON/text 输出中列出失败项。真实 desktop、raw/hid、YOLO 测试仍为 opt-in，不进入默认 release gate。
