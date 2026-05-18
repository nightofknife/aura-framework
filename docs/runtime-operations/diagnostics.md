# Diagnostics

Aura 提供本地 diagnostics bundle，用于长期运行排障和升级讨论。diagnostics 默认脱敏，默认不复制截图/OCR 原始 evidence 文件。

## CLI

```powershell
python cli.py diagnostics collect
python cli.py diagnostics collect --output diagnostics/latest.zip
python cli.py diagnostics collect --include-evidence
python cli.py diagnostics recent
```

## API

- `GET /api/v1/diagnostics/recent`
- `GET /api/v1/diagnostics/{id}`
- `POST /api/v1/diagnostics/collect`

## Bundle 内容

- `manifest.json`
- `system.json`
- `workspace.json`
- `packages.json`
- `capabilities.json`
- `runs.json`
- `run-details/`
- `logs/`
- `config.redacted.json`
- `evidence/`，默认只包含 manifest 和 action result 引用

## 脱敏规则

默认脱敏包含以下关键字的字段：

- `api key`
- `token`
- `password`
- `secret`
- `cookie`
- `authorization`

diagnostics 不扫描用户任意目录，只收集 Aura 已知路径下的配置、日志、运行记录和 evidence 引用。

## Evidence 导出

默认只导出：

- `logs/evidence/{cid}/manifest.json`
- `logs/evidence/{cid}/action-results.jsonl`

只有显式传入 `--include-evidence` 时，才复制 action result 已记录路径下的 `captures/`、`ocr/`、`backend/` 文件。不会导出未被 run detail 引用的文件。
