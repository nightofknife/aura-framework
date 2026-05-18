# Evidence and Run Detail

V4 之后，Aura 将 action return、desktop backend result、policy decision、fallback 和 evidence reference 收敛到统一 run detail。Roadmap Closure 在此基础上补齐 locator/OCR/YOLO/window/capture 诊断链。

## Action Result Envelope

```json
{
  "ok": true,
  "action": "plans/aura_base/click",
  "backend": "win32_sendinput",
  "capabilities_used": ["desktop.mouse.input"],
  "policy": {
    "profile": "default",
    "decision": "allow",
    "reason": ""
  },
  "duration_ms": 12,
  "data": {
    "value": {},
    "rendered_params": {}
  },
  "evidence": [],
  "fallbacks": []
}
```

原 action return 保留在 `data.value`，避免破坏 task outputs。渲染后的参数保留在 `data.rendered_params`，用于 debug report 和 `run explain`。

## Evidence Store

```text
logs/evidence/{cid}/
  manifest.json
  action-results.jsonl
  captures/
  locators/
  ocr/
  yolo/
  window/
  backend/
```

SQLite 表：

- `action_results`
- `policy_audit`
- `evidence_refs`

## Evidence Manifest Domains

- `captures`: capture image refs、region、backend、quality flags。
- `locators`: selected candidate、all candidates、threshold、failure reason。
- `ocr`: recognized boxes、text、confidence、source image ref。
- `yolo`: model ref、class labels、detections、confidence、source image ref。
- `window`: title、hwnd、rect、client rect、dpi、foreground/minimized state。
- `backend`: selected backend、fallback reason、unavailable reason。

## Run Detail API

- `GET /api/v1/runs/{cid}`: 保持旧字段，只增 `action_results`、`policy_decisions`、`evidence`。
- `GET /api/v1/runs/{cid}/evidence`: 兼容 evidence manifest 入口。
- `GET /api/v1/runs/{cid}/evidence/manifest`: 返回分域 evidence manifest，不返回二进制文件。
- `GET /api/v1/runs/{cid}/locators`: 返回定位结果和候选列表。
- `GET /api/v1/runs/{cid}/debug-report`: 聚合 failed nodes、rendered params、policy、backend/fallback、locator 和 evidence manifest。

## Diagnostics

diagnostics 默认只导出 evidence manifest。只有显式 `--include-evidence` 才复制 evidence 文件，并且只复制 run detail 已记录路径下的文件。

## Failure Questions

失败 run 至少应能回答：

- 哪个 action、哪个 node 失败。
- 渲染后的 params 是什么。
- 使用了哪个 backend，为什么 fallback 或为什么不可用。
- policy 为什么 allow 或 deny。
- locator/OCR/YOLO 候选是什么，阈值是多少。
- evidence reference 在哪里。
