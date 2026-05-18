# Aura V2 桌面能力多 Backend 提升方案

V2 将 `plans/aura_base` 收敛为 Windows desktop capability runtime。截图、鼠标、键盘、窗口、OCR 统一通过 capability registry、desktop facade、backend selection policy、fallback 和结构化诊断运行。

## 目标

- 建立 `capture`、`mouse`、`keyboard`、`window`、`ocr` 五类能力注册表。
- 保留现有 `ScreenService`、`ControllerService`、`AppProviderService` API，内部逐步接入统一 facade。
- 让 plan 作者可以显式选择 backend，或使用 `default/safe/fast/background/raw` profile。
- 将 backend 选择、fallback、失败原因和 evidence 写成统一结构，供 run detail 和 GUI 消费。
- 提供 fake backend，支撑 CI、dry-run 和无副作用测试。

## Backend 范围

V2 默认声明以下 backend：

- capture: `gdi`, `mss`, `dxgi`, `printwindow`, `fake`
- mouse: `win32_mouse_event`, `win32_sendinput`, `win32_postmessage`, `raw_input`, `hid_mouse`, `uia`, `fake`
- keyboard: `win32_keybd_event`, `win32_sendinput`, `win32_postmessage`, `clipboard_paste`, `uia`, `fake`
- window: `win32`, `uia`, `fake`
- ocr: `paddleocr`, `fake`

`raw_input` 是监听和诊断 backend，用于记录真实鼠标事件、校准、录制和验证目标应用是否使用 Raw Input。它不承诺注入鼠标事件。

`hid_mouse` 是原始输入注入 backend，需要本机已有虚拟 HID 或 Interception 类驱动。V2 不安装、不捆绑驱动；未检测到驱动时必须返回 `available=false` 和明确原因。

## 稳定接口

能力查询 API：

- `GET /api/v1/capabilities`
- `GET /api/v1/capabilities/{domain}`
- `POST /api/v1/capabilities/self-check`

统一 backend metadata：

- `backend_id`
- `domain`
- `available`
- `health_status`
- `requires_foreground`
- `supports_background`
- `supports_minimized`
- `requires_admin`
- `side_effect_level`
- `capabilities`
- `limitations`
- `last_error`
- `stability`

统一 result model：

```json
{
  "ok": true,
  "backend": "win32_sendinput",
  "domain": "mouse",
  "operation": "click",
  "data": {},
  "error_code": null,
  "message": "",
  "duration_ms": 12,
  "evidence": [],
  "fallbacks": []
}
```

## 选择策略

默认 profile：

- `default`: 稳定优先。截图 `gdi -> mss -> dxgi`，输入 `win32_sendinput -> compat backend`。
- `safe`: 语义和低副作用优先。优先 `uia`、`clipboard_paste`。
- `fast`: 性能优先。截图优先 `dxgi`。
- `background`: 后台窗口优先。截图优先 `printwindow`，输入优先 `postmessage/uia`。
- `raw`: 原始输入优先。鼠标优先 `hid_mouse`，不可用时回退 `win32_sendinput`。

Task DSL 可显式指定：

```yaml
with:
  backend: win32_sendinput
```

或指定 fallback：

```yaml
with:
  backend:
    prefer: dxgi
    fallback: [gdi, mss]
```

显式指定 backend 且无 fallback 时，不可用即报错。

## V2 验收标准

- `/capabilities` 能返回所有默认 backend 的完整 metadata。
- `ScreenService` 可以列出 `gdi/mss/dxgi/printwindow/fake` 并执行 fake capture。
- `ControllerService` 可以通过 facade 选择 mouse/keyboard backend。
- `raw_input` 能规范化真实鼠标事件数据；`hid_mouse` 未配置驱动时稳定显示 unavailable。
- fake backend 可用于无副作用测试。
- GUI 设置页能只读展示当前 desktop capability 可用情况。
- V1 的 API、GUI 默认导航和 workspace-default 启动方式不被破坏。
