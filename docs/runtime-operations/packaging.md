# Aura Packaging

Aura release artifacts are split into three independent deliverables:

- `AuraRuntime-win-x64-{version}.zip`: Core Runtime, CLI, API, scheduler, and package lifecycle.
- `AuraGUI-win-x64-{version}.zip`: Electron portable GUI that discovers local Runtime through the runtime registry.
- `aura_base-{version}.aura`: official desktop capability package, installed with the same flow as user packages.

Build all release artifacts:

```powershell
python cli.py release pack --version 0.1.0 --output dist/release
```

`release pack` runs `release check` first. If the gate fails, no release artifacts are produced. On success it writes `release-manifest.json` and `checksums.sha256`.

## Runtime

Runtime zip does not include `.venv`, logs, SQLite databases, tokens, GUI assets, `node_modules`, or local-only assets. The default `workspace.yaml` has an empty package set; `aura_base` must be installed as a `.aura` package.

Deploy:

```powershell
Expand-Archive AuraRuntime-win-x64-0.1.0.zip C:\Aura
cd C:\Aura\AuraRuntime
.\scripts\install_runtime.ps1
.\scripts\start_runtime.ps1
```

For a click-to-run local runtime, double click:

```text
C:\Aura\AuraRuntime\AuraRuntime.cmd
```

`AuraRuntime.cmd` runs `scripts\run_runtime.ps1`. On first run it creates the
venv by calling `install_runtime.ps1`; after that it starts Runtime directly.

Runtime and GUI share the same default information endpoint:

```text
http://127.0.0.1:18098/api/v1
ws://127.0.0.1:18098
```

`start_runtime.ps1` writes `%LOCALAPPDATA%\Aura\runtime-registry.json` for the
Electron GUI. Registry entries include `host`, `port`, `info_port`, `api_base`,
`ws_base`, and `token_path`.

## GUI

The first GUI distribution is an Electron portable zip. The GUI does not directly edit packages, workspace files, or lock files; it calls Runtime APIs.

```powershell
Expand-Archive AuraGUI-win-x64-0.1.0.zip C:\Aura\AuraGUI
C:\Aura\AuraGUI\Aura.exe
```

## Package

`.aura` is a zip format:

```text
manifest.yaml
package/
checksums.sha256
package-lock.snapshot.yaml
compat-report.json
fixtures/
migrations/
```

During package build, development module paths such as `plans.aura_base.src.services.screen_service` are rewritten to package-relative paths such as `src.services.screen_service`. After install, Runtime places the package under `packages/{leaf}` and derives the import prefix from that path.

Install the official base package:

```powershell
python cli.py package install C:\Downloads\aura_base-0.1.0.aura
python cli.py package validate plans/aura_base
python cli.py package deps doctor plans/aura_base
python cli.py package deps plan plans/aura_base
# Only when dependencies are missing and the package is trusted:
# $env:AURA_POLICY_PROFILE="trusted"
# python cli.py package deps install plans/aura_base --apply --trusted --allow-network
python cli.py package lock
python cli.py package reload plans/aura_base --drain
```

Dependency installation is explicit. `package install` never silently runs `pip`.
Use `package deps doctor` to inspect requirements, `package deps plan` to review
the pip command, and `package deps install --apply --trusted --allow-network`
only after the package and network access are intentionally approved. The active
policy profile must allow both `filesystem.write` and `network.remote`.
