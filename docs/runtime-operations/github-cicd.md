# GitHub CI/CD

Aura 的 GitHub Actions 分为四条流水线：

- `PR CI`: PR 和 main push 的快速门禁，覆盖 runtime preflight、默认 pytest、GUI build、契约与安全检查。
- `Release Check`: main 分支 release readiness，直接执行 `python cli.py release check`。
- `Release Pack`: tag 或手动触发时生成三段式产物，并运行 artifact smoke。
- `Opt-in Desktop Validation`: 手动触发真实桌面、YOLO、raw input、HID、slow marker 验证。

默认 CI 不运行真实桌面副作用测试。真实 desktop/raw/hid/yolo 测试必须通过 `workflow_dispatch` 显式打开。

## PR Gate

PR 必须通过：

```powershell
.\scripts\build_preflight.ps1
.\scripts\run_tests.ps1
npm run build
python cli.py core smoke --profile framework-core --minimal-workspace
python cli.py validate --strict
python cli.py package doctor --format json
python cli.py package deps doctor plans/aura_base --format json
python cli.py policy doctor
python cli.py sdk doctor
python cli.py migration status
python cli.py compat check --format json
python cli.py fixture verify-all --format json
```

## Release Gate

`Release Check` 只调用统一本地门禁：

```powershell
python cli.py release check
```

该命令聚合 core smoke、strict validate、package doctor、dependency doctor、policy、SDK、migration、compat、fixtures、pytest 和 GUI build。

## Release Pack

tag `v*` 或手动传入 version 后执行：

```powershell
python cli.py release pack --version 0.1.0 --output dist/release
python scripts/verify_release_artifacts.py --release-dir dist/release --version 0.1.0
```

产物：

- `AuraRuntime-win-x64-{version}.zip`
- `AuraGUI-win-x64-{version}.zip`
- `aura_base-{version}.aura`
- `release-manifest.json`
- `checksums.sha256`

`verify_release_artifacts.py` 会检查 checksums、manifest、Runtime 双击入口、默认端口、GUI 可执行文件、`.aura` 包结构，以及 Runtime zip 中不得包含 logs、token、sqlite、venv、node_modules、`lsns` 等本地或生成资产。
