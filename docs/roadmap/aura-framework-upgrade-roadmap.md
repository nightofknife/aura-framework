# Aura 通用 Windows 桌面自动化框架提升路线

本文档用于指导 Aura 从当前 `Windows 本机桌面自动化工作区` 逐步升级为 `通用 Windows 桌面自动化框架`。它既记录产品方向，也提供后续工程拆解的路线依据。

本文档不做具体业务方案设计，不恢复或迁移已清理业务资产。

## 1. 当前定位与目标定位

### 当前定位

Aura 当前更接近一个本机工作区：

- 运行平台固定为 Windows、PowerShell、Python 3.13、`venv`。
- 默认 runtime 使用 `workspace-default` 依赖档。
- 当前工作区会 eager-import `plans/aura_base` 的 service / action。
- `framework-core` 仍主要用于未来最小 smoke 或拆仓准备。
- GUI 当前以本地任务选择、派发、队列和运行观察为主。

### 目标定位

Aura 的目标是成为通用 Windows 桌面自动化框架：

- core 能独立提供调度、DSL、package、API、observability、安全边界。
- desktop capability 作为官方能力包提供截图、键鼠、OCR、视觉、YOLO、进程管理等能力。
- plan 作者可以基于稳定 DSL、manifest、action/service SDK 和工具链开发自动化方案。
- 本地 GUI 作为控制台，优先服务任务执行、运行观测、调试和开发辅助。
- API、DSL、manifest、action/service contract 具备清晰版本和兼容策略。

## 2. 当前框架能力基线

当前 Aura 已具备以下基础能力：

- **Scheduler**：独立线程运行 asyncio control loop，管理主队列、事件队列、中断队列和生命周期。
- **Plan / Package**：通过 `manifest.yaml` 发现、校验、加载 plan/package，并注册 action、service、task。
- **Task DSL**：支持 `meta.inputs`、DAG `depends_on`、`when`、`loop`、重试、超时、`outputs`、`returns` 和 `aura.run_task`。
- **Execution Engine**：按 DAG 调度 step，由 NodeExecutor 负责 action 调用、模板渲染、循环、重试和运行状态写入。
- **FastAPI 控制面**：提供 system、plans/tasks、dispatch、queue、runs、catalog 等最小平台 API。
- **Vue GUI**：提供本地执行台、运行记录、方案/任务和设置等 V1 控制台能力。
- **Desktop capability**：`plans/aura_base` 已提供 screen、controller、vision、ocr、process manager、navigation、YOLO 等能力。
- **Observability**：已有事件总线、运行快照、RunStore、metrics、日志和 UI event queue。
- **Security**：默认 `local_only`，远程模式需要显式开启 API key、trusted hosts 和相关 feature flag。

这些能力足以支撑本地自动化运行，但还不足以让第三方稳定地把 Aura 当作通用框架长期构建方案。

## 3. 主要不足清单

### 3.1 Core 与 desktop capability 耦合

当前默认运行时需要覆盖 `plans/aura_base` 的硬依赖，core 还不能作为真正的最小框架独立运行。通用框架需要把 scheduler、DSL、package、API 等核心能力与桌面能力包分层。

### 3.2 Package 产品化闭环不足

manifest、dependency、exports、resources、lifecycle 已有模型，但缺少完整的安装、升级、锁定、校验、打包、发布和兼容检查流程。

### 3.3 API / GUI 契约不完全一致

后端当前主打 minimal API，但 GUI 代码中仍保留部分面向 Actions、Services、Packages、Automation、Dashboard 的未来或兼容调用。需要明确哪些是 V1 稳定接口，哪些是兼容接口，哪些暂不承诺。

### 3.4 DSL 作者体验不足

任务 DSL 已经可用，但作者缺少高质量工具链：

- 静态 lint
- schema 校验
- dry-run
- task_ref 检查
- depends_on 可视化
- 模板表达式调试
- 输入 schema 预览
- action 参数提示
- 错误定位到文件、任务、step、字段

### 3.5 调试和失败诊断能力不足

当前 runs/nodes/timeline 有基础数据，但自动化开发需要更强的诊断闭环：

- 失败节点的渲染后 params
- 失败时截图和窗口信息
- OCR / vision / YOLO 的匹配详情
- step 级耗时和 retry 详情
- 单 step 重跑
- 指定 task + inputs 的调试报告
- 可导出的诊断包

### 3.6 桌面自动化抽象层不统一

screen、vision、ocr、yolo、controller 能力丰富，但结果模型和上下文抽象还不统一。通用框架需要统一窗口上下文、截图结果、定位结果、动作结果、坐标体系和失败原因。

### 3.7 Action / Service 权限模型不足

当前安全边界主要在 API 访问层和高风险接口 feature flag。通用框架需要 action/service 级能力声明，例如：

- 文件读写
- 进程启动
- 键鼠控制
- 屏幕截图
- 网络访问
- 热重载
- plan 文件编辑

### 3.8 持久化能力偏弱

当前 file store 和 RunStore 足够本地使用，但还不够支撑长期运行、历史查询和升级迁移。数据库持久化、schema 版本、历史清理策略和导出能力仍需补齐。

### 3.9 Observability 不够工程化

已有 metrics、events、logs，但还缺少面向问题定位的结构化模型：

- trace 查询
- 错误分类
- action/service 耗时统计
- capture / OCR / YOLO 耗时统计
- 队列等待和资源竞争分析
- 任务级资源占用

### 3.10 测试缺少真实自动化夹具和端到端验收

当前测试覆盖 API、安全、调度、YOLO smoke、桌面 service import 等基础回归。还需要：

- fake screen backend
- 固定截图夹具
- vision golden tests
- OCR 解析夹具
- action 注入端到端测试
- minimal plan 执行测试
- GUI/API 契约测试

### 3.11 GUI 产品形态未收敛

GUI 当前既有 V1 执行台能力，也保留了一些更像未来控制台或 IDE 的页面。下一步需要明确 GUI 是轻量运行控制台，还是逐步升级为 authoring/debugging 控制台。短期应优先收敛 API 契约和执行观测。

### 3.12 版本化与兼容策略不足

DSL、manifest、REST API、action FQID、service contract 都需要版本承诺。通用框架必须降低 plan 作者升级成本，避免写好的方案因隐式行为变化而失效。

## 4. 升级原则

- **先框架，后业务**：不把具体业务方案设计作为框架路线的一部分。
- **先收敛契约，再扩展界面**：GUI 新能力必须建立在稳定 API 之上。
- **core 最小可用**：核心 runtime 应能在不加载 desktop capability 的情况下完成 smoke。
- **能力包显式化**：desktop capability 作为官方 package，而不是隐式混入框架本体。
- **诊断优先于自动修复**：先让失败可定位，再做高级恢复和智能规划。
- **兼容可声明**：DSL、manifest、API 和 package contract 的破坏性变化必须有版本边界。
- **测试围绕用户路径**：不仅测函数，还要测 plan 作者和运行用户的关键流程。

## 5. 四阶段提升路线

## Phase 1：框架核心收敛

目标：让 Aura 从本机工作区收敛为清晰分层的框架底座。

重点工作：

- 拆清 `aura_core` 与 desktop capability 的边界。
- 确认 `framework-core` 的最小依赖档，并补齐独立 smoke。
- 将 `workspace-default` 定义为默认工作区 profile，而不是框架 core 的必需依赖。
- 收敛 API v1：明确 stable、compat、experimental 三类接口。
- 清理 GUI 中未对齐 API 的入口，或标注为隐藏/实验能力。
- 明确 runtime profile：`api_full`、`tui_manual` 的职责和未来扩展边界。
- 文档中同步更新当前定位，避免“工作区”和“框架”表述混用。

阶段验收：

- 使用 `framework-core` 依赖档可以完成 core import、create runtime、load empty/minimal plan、API health smoke。
- `workspace-default` 仍能启动完整本地工作区。
- REST API 文档、后端 routes、GUI V1 调用表面一致。
- 没有具体业务资产被纳入框架路线。

## Phase 2：开发者体验与 DSL 工具链

目标：让 plan 作者能稳定、高效地编写和调试任务。

重点工作：

- 增加 `aura validate` 或等价 CLI，校验 manifest、task YAML、task_ref、depends_on、inputs。
- 增加 task dry-run：解析 task、渲染静态结构、检查 action 参数，不执行键鼠/截图等副作用动作。
- 输出 task 依赖图，用于 CLI 或 GUI 展示。
- 为 action/service 生成文档：参数、返回、依赖服务、read_only、风险能力。
- 增强错误信息：包含 plan、task_ref、task_key、step_id、字段路径和修复建议。
- 为模板表达式增加调试入口，显示可用作用域和渲染结果。
- 提供最小 plan 模板和 package scaffold。

阶段验收：

- 新 plan 作者可以通过模板创建一个最小 plan。
- 错误 task YAML 可以得到结构化错误，而不是只在日志中失败。
- GUI 能展示 task inputs 和基础校验错误。
- action catalog 能作为作者参考文档使用。

## Phase 3：桌面自动化能力抽象升级

目标：把现有桌面能力从 action 集合升级为一致、可测试、可诊断的能力层。

重点工作：

- 定义统一的 `WindowContext`，包含目标窗口、client rect、DPI、坐标原点、capture backend。
- 定义统一的 `CaptureResult`、`LocatorResult`、`ActionResult`。
- image / text / yolo 定位动作统一返回 bbox、center、score、source、backend、timestamp。
- controller 动作统一返回执行结果、目标坐标、耗时和失败原因。
- 增加 fake screen backend，用固定图片替代真实屏幕。
- 为 vision/OCR/YOLO 增加 golden test 夹具。
- 建立失败截图、匹配可视化和诊断附件机制。

阶段验收：

- 不依赖真实桌面环境即可运行核心 desktop capability 测试。
- 一次定位失败可以从结果中看出截图来源、匹配方法、阈值和失败原因。
- 任务失败详情能关联截图、定位结果和 action 参数。

## Phase 4：产品化与长期运行

目标：让 Aura 支撑长期运行、团队复用和版本升级。

重点工作：

- 设计 package 安装、升级、锁文件和兼容检查流程。
- 引入持久化后端版本策略，补齐数据库持久化或可替代的长期存储。
- 完善 run history、timeline、diagnostic bundle 的导出能力。
- 建立 API、DSL、manifest、action/service contract 的版本策略。
- 加强权限模型，按 action/service capability 做声明和限制。
- 为 GUI 增加稳定的运行观测和诊断入口。
- 建立 release checklist 和升级指南。

阶段验收：

- package 可以被安装、校验、升级，并能发现不兼容变更。
- 长期运行历史可查询、清理、导出。
- 版本升级有明确兼容说明。
- 安全配置可以限制高风险能力。

## 6. 推荐优先级

短期优先做三件事：

1. **Core 与 desktop capability 解耦**
   - 这是通用框架定位的基础。
   - 如果 core 不能最小运行，后续 package 产品化和测试都会继续受工作区耦合影响。

2. **API / GUI 契约收敛**
   - 先明确 V1 稳定表面，避免 GUI 和后端相互拖拽。
   - 未实现的详情接口要么补齐，要么隐藏对应页面。

3. **Task DSL 校验和调试工具链**
   - 这是 plan 作者最直接的生产力入口。
   - 校验、dry-run、错误定位能显著降低使用门槛。

中期再推进：

- 统一 desktop result model。
- fake backend 和 golden tests。
- action/service 权限模型。
- run diagnostic bundle。

长期推进：

- package install/upgrade。
- 持久化升级。
- 版本兼容策略。
- GUI authoring/debugging 能力。

## 7. 验收标准

当 Aura 可以被称为通用 Windows 桌面自动化框架时，至少应满足：

- `framework-core` 可独立完成 smoke，不强依赖 desktop capability。
- `workspace-default` 只是默认工作区 profile，而不是框架 core 的隐式定义。
- API 文档、后端测试、GUI 调用表面一致。
- 新 plan 作者能通过文档、模板、校验工具完成最小任务开发。
- 自动化失败能产出可定位原因的结构化运行详情。
- action/service 能力边界可声明、可检查。
- package/plan 有明确版本和兼容策略。
- 核心 desktop capability 可以通过 fake backend 在 CI 中验收。

## 8. 风险与非目标

### 风险

- 过早扩展 GUI 会放大 API 契约不稳定的问题。
- 继续把 desktop capability 绑定在 core 里，会阻碍框架最小化和测试分层。
- 没有版本策略时，DSL 和 manifest 的每次语义调整都会伤害 plan 作者信任。
- 只补 action 数量而不补诊断，会让复杂自动化更难维护。

### 非目标

- 不做具体业务方案设计。
- 不恢复或迁移已清理业务资产。
- 不在本路线中引入 Docker、Poetry、`pyproject.toml` 或 Windows Service 安装器，除非后续另立技术决策。
- 不把 GUI 直接扩成完整 IDE，除非先完成 API 契约收敛和 DSL 工具链。
- 不承诺跨平台桌面自动化；当前目标仍是 Windows。

## 9. 后续议题池

后续可以基于本路线继续拆分以下专题：

- Core / desktop capability 解耦设计。
- API v1 stable / compat / experimental 分类。
- Task DSL lint 与 dry-run 规范。
- Action/service capability 权限模型。
- Desktop result model 统一规范。
- Fake screen backend 与视觉测试夹具。
- Run diagnostic bundle 格式。
- Package 安装、升级和 lock 设计。
- GUI V1 控制台收敛方案。
- 版本策略与兼容矩阵。
