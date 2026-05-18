# Aura Roadmap Closure 全量补齐方案

## 定位

Roadmap Closure 用于收口 `aura-framework-upgrade-roadmap.md` 在 V1-V6 后仍未完全闭环的能力。目标不是引入新的产品方向，而是把 Aura 当前本地 Windows 桌面自动化框架基线补到可验证、可诊断、可升级、可发布。

本轮继续遵守既有非目标：

- 不恢复或引用已清理业务资产。
- 不做远程 marketplace。
- 不引入 Docker、Poetry、pyproject。
- 不把 GUI 扩展为完整 IDE。
- 不承诺跨平台，目标环境仍是 Windows 本机、PowerShell、Python 3.13、venv。

## 实施范围

### 1. Core 最小发行边界

新增 `framework-core` 本地 profile 与 core smoke 验证入口：

```powershell
python cli.py core smoke --profile framework-core --minimal-workspace
```

该命令验证：

- `packages.aura_core` 可导入。
- scheduler/runtime 可创建。
- 空或 minimal workspace 可加载。
- FastAPI app 可初始化并通过 `/api/v1/system/health`。
- smoke 期间不加载 `plans.aura_base`、PaddleOCR、OpenCV、pywin32、ultralytics。

这把 `aura_core`、`plans/aura_base`、`workspace-default` 三者边界从文档约定推进为自动化约束。后续拆仓或独立发行可以以该 profile 为候选边界，本轮仍不拆仓。

### 2. Desktop Facade 与统一结果

desktop runtime 增加统一数据模型：

- `WindowContext`
- `CaptureResult`
- `LocatorResult`
- `DesktopActionResult`

fake/fixture backend 已支持 capture、window、OCR、locator、YOLO 诊断数据。稳定输入 action 继续通过 facade 选择 backend，`raw_input` 保持 monitor，`hid_mouse` 仍是可选驱动 backend，显式请求不可用时失败，只有 DSL 写明 fallback 时才回退。

坐标模型固定为：

- 默认 `client`
- 可选 `screen`、`window`、`client`、`normalized`

### 3. Evidence、Locator 与 Debug Report

run store 增加只读诊断查询：

- `GET /api/v1/runs/{cid}/debug-report`
- `GET /api/v1/runs/{cid}/locators`
- `GET /api/v1/runs/{cid}/evidence/manifest`

失败路径会把 action result、rendered params、policy decision、backend、fallback、locator evidence、window/capture/OCR/YOLO refs 聚合到 debug report。diagnostics 默认只导出 evidence manifest，不复制截图/OCR 原始二进制。

CLI `run explain` 继续作为终端定位入口，输出错误分类、policy、backend/fallback、evidence refs 与下一步建议。

### 4. Golden Fixtures

fixture schema 升级到 v2，兼容 v1。新增固定矩阵：

- `capture/basic-screen`
- `vision/template-match`
- `ocr/simple-text`
- `yolo/simple-detections`
- `window/basic-context`
- `task/minimal-fake-e2e`
- `failure/locator-not-found`

新增命令：

```powershell
python cli.py fixture doctor
python cli.py fixture verify-all --format text
python cli.py fixture update NAME --snapshot-only
```

`fixture verify-all` 使用 fake/fixture backend，不触发真实截图、键鼠、OCR、YOLO、进程或文件写入副作用，并纳入 release check。

### 5. Observability 深度指标

observability 在 V5 基础上增加：

- service latency
- desktop domain metrics
- resource samples
- category drilldown

新增 API：

- `GET /api/v1/observability/metrics/services`
- `GET /api/v1/observability/metrics/desktop`
- `GET /api/v1/observability/resources`
- `GET /api/v1/observability/errors/{category}`

错误分类继续复用 V4/V5 的 action envelope、policy audit、evidence refs 和 run nodes，不引入第二套事件模型。

### 6. Package Upgrade 执行闭环

package lifecycle 增加本地 upgrade executor：

```powershell
python cli.py package upgrade PACKAGE_ID --from PATH --dry-run
python cli.py package upgrade PACKAGE_ID --from PATH --apply
python cli.py package rollback PACKAGE_ID --to-lock packages.lock.yaml
python cli.py package migrations PACKAGE_ID
```

行为约定：

- `--dry-run` 只生成 plan，不修改 workspace、lock 或 package files。
- `--apply` 先 validate、diff，再备份当前 package、替换文件、写 lock，并记录 upgrade operation。
- apply 失败时恢复 package files、workspace profile 和 lock。
- 只支持本地目录、zip、`.aura`。

`.aura` 包可包含 `compat-report.json`、`fixtures/`、`migrations/`。manifest 可选 `compat` 区用于声明 Aura 最低版本、DSL 版本、弃用 action 和 migration hooks。

### 7. Compatibility Governance

兼容治理扩展了 stable contract snapshot：

- API path/method snapshot。
- stable action FQID 与参数 snapshot。
- stable service snapshot。
- task DSL、manifest、desktop result、evidence schema 引用。

新增命令：

```powershell
python cli.py compat snapshot --update
```

默认 `compat check` 只比较，不更新快照。删除 stable API、移除 action 参数、删除 stable service 都会被兼容检查捕获。

### 8. GUI 轻量入口

GUI 保持运行与观测控制台形态，不做在线 YAML/manifest 编辑。

新增或增强：

- Plans: task graph、task explain 基础信息、validate、dry-run、action parameter schema 只读提示。
- Runs: debug report drawer、locator/evidence tab。
- Packages: local upgrade dry-run result；apply 按钮默认受 local admin feature flag 隐藏。
- Observability: error category drilldown、desktop metrics、service latency、resource samples。

## 验收命令

```powershell
.venv-test\Scripts\python.exe cli.py core smoke --profile framework-core --minimal-workspace
.venv-test\Scripts\python.exe cli.py fixture verify-all --format json
.venv-test\Scripts\python.exe cli.py compat check
.venv-test\Scripts\python.exe -m pytest tests\test_roadmap_closure.py
npm.cmd run build
```

默认发布门禁仍由 `python cli.py release check` 聚合执行。

## 完成标准

- `framework-core` 可被自动验证为不依赖 desktop capability。
- fake/fixture golden matrix 可在无真实桌面副作用下验收核心 desktop capability。
- run detail/debug report 可以定位 rendered params、policy、backend、fallback、locator/OCR/YOLO evidence。
- observability 能按 trace、错误类型、action/service、desktop backend、resource/queue 维度查询。
- package 可本地 dry-run upgrade、apply upgrade、rollback。
- GUI 保持控制台形态，但能完成 validate、dry-run、graph、debug report、fake evidence 和 upgrade-plan 的轻量操作。
