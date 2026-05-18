# Policy Capability Reference

Aura V4 引入 action/service capability policy。policy 在 action resolve 之后、参数调用之前执行；拒绝时抛出 `PolicyDeniedError`，并把 deny 记录写入 run detail 和 audit。

## Capability Taxonomy

- `desktop.capture.read`
- `desktop.window.read`
- `desktop.window.focus`
- `desktop.mouse.input`
- `desktop.keyboard.input`
- `desktop.raw_input.monitor`
- `desktop.hid.input`
- `desktop.ocr.read`
- `process.read`
- `process.control`
- `filesystem.read`
- `filesystem.write`
- `network.local`
- `network.remote`

## Decorator Metadata

```python
@action_info(
    name="click",
    capabilities=["desktop.mouse.input"],
    side_effect_level="input",
    requires_foreground=True,
    requires_admin=False,
    stability="stable",
)
def click(...):
    ...
```

`@service_info` 支持同样的 metadata 字段。

默认值：

- `capabilities=[]`
- `side_effect_level="read"` if `read_only=True` else `"input"`
- `requires_foreground=False`
- `requires_admin=False`
- `stability="stable"`

## Profiles

### safe

允许 read、OCR、window read。拒绝键鼠注入、HID、raw monitor、process control、filesystem write、remote network。

### default

允许常规 capture/window/mouse/keyboard/OCR、本地文件读写、本地网络。拒绝：

- `desktop.hid.input`
- `process.control`
- `network.remote`

### trusted

允许 package 显式声明的所有 capability。

### dev

允许实验能力，适合本机开发诊断。

## CLI

```powershell
python cli.py policy inspect
python cli.py policy doctor
python cli.py package permissions plans/aura_base
```

`policy doctor` 检查 stable action/service 是否缺少显式 capability metadata。当前兼容期会保留推断能力，但新 stable action 应显式声明。

## API

- `GET /api/v1/policy`
- `GET /api/v1/policy/effective`
- `GET /api/v1/workspace/packages/{package_id}/permissions`

## Backend 选择与 policy

如果 action 参数显式使用 `hid_mouse`，即使 action 只声明 `desktop.mouse.input`，policy 也会把本次调用增强为 `desktop.hid.input` 并按 profile 判定。

显式 backend 不可用时默认失败；只有 DSL 写明 fallback 时才回退。
