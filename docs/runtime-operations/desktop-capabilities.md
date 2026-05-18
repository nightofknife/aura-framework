# Desktop Capability Backend Matrix

`plans/aura_base` 是官方 desktop capability package。V2/V4 后，桌面能力通过 registry、facade、backend selection、fake backend 和结构化 result model 逐步收敛。

`available=false` 不是运行错误，它表示当前机器缺依赖、缺权限、缺驱动或 backend 不适用于当前环境。

## Facade Domains

- `capture`: `capture_screen`、`capture_window`、`capture_region`
- `mouse`: `move`、`click`、`double_click`、`down`、`up`、`drag`、`scroll`
- `keyboard`: `key_down`、`key_up`、`press`、`hotkey`、`type_text`、`paste_text`
- `window`: `list_windows`、`find_window`、`focus`、`get_rect`、`get_client_rect`
- `ocr`: `recognize`、`find_text`

默认坐标系是 `client`。action 未显式传入 `coordinate_space` 时，按当前兼容行为把客户区坐标转换为全局屏幕坐标。

## Capture

| Backend | 场景 | 后台窗口 | 最小化 | 多屏 | 限制 |
| --- | --- | --- | --- | --- | --- |
| `gdi` | 默认稳定截图、窗口客户区截图 | 部分支持 | 否 | 主屏为主 | GPU/受保护表面可能黑屏 |
| `mss` | 区域截图、多屏 | 否 | 否 | 是 | optional dependency |
| `dxgi` | 高频截图、动态画面 | 否 | 否 | 依赖实现 | optional dependency，部分窗口不可见 |
| `printwindow` | 指定窗口后台截图 | 部分支持 | 否 | 不适用 | 很多 GPU 窗口会拒绝或返回空帧 |
| `fake` | dry-run、CI、E2E fixture | 是 | 是 | 是 | 不代表真实屏幕 |

## Mouse

| Backend | 场景 | 后台 | 原始输入 | 限制 |
| --- | --- | --- | --- | --- |
| `win32_sendinput` | 默认低层输入注入 | 否 | 否 | 需要前台焦点，可能被高完整性应用拦截 |
| `win32_mouse_event` | 兼容旧实现 | 否 | 否 | compat backend，不作为长期首选 |
| `win32_postmessage` | 部分后台窗口消息 | 部分 | 否 | 目标应用可能忽略消息 |
| `raw_input` | 监听、录制、校准、诊断 | 是 | 监听 | Raw Input 不注入事件 |
| `hid_mouse` | 虚拟 HID/Interception 注入 | 依赖驱动 | 是 | 需要本机预装驱动和权限；不可用时必须明确报 unavailable |
| `uia` | 语义控件点击 | 部分 | 否 | 需要 UIA 支持 |
| `fake` | dry-run、CI、E2E fixture | 是 | 模拟 | 不操作真实鼠标 |

## Keyboard

| Backend | 场景 | 后台 | 限制 |
| --- | --- | --- | --- |
| `win32_sendinput` | 默认低层键盘输入 | 否 | 需要前台焦点 |
| `win32_keybd_event` | 兼容旧实现 | 否 | compat backend |
| `win32_postmessage` | 部分后台窗口消息 | 部分 | 目标应用可能忽略消息 |
| `clipboard_paste` | 大段文本输入 | 部分 | 临时修改剪贴板 |
| `uia` | 文本框语义输入 | 部分 | 需要 UIA 支持 |
| `fake` | dry-run、CI、E2E fixture | 是 | 不操作真实键盘 |

## Raw Input 边界

Windows Raw Input API 用于接收硬件输入事件。Aura 的 `raw_input` backend 只用于监听和诊断：记录相对移动、按钮、滚轮和设备信息。

需要“原始输入注入”时使用 `hid_mouse`。`hid_mouse` 不安装也不捆绑第三方内核驱动，只适配本机已有的虚拟 HID / Interception 类驱动；未检测到驱动时必须返回 `available=false` 和明确原因。

## Result Model

desktop facade 返回统一结果：

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

`DesktopResult` 会被执行引擎包装进 action result envelope，并进入 run detail 与 evidence manifest。
