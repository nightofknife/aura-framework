param(
    [string]$BasePython = "C:\Python313\python.exe",
    [string]$VenvPath = ".venv",
    [switch]$UseLock = $true
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

try {
    if (-not (Test-Path $BasePython)) {
        throw "Base Python not found: $BasePython"
    }

    $version = & $BasePython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    if (-not $version.StartsWith("3.13.")) {
        throw "Base Python must be 3.13.x. Current: $version"
    }

    if (-not (Test-Path $VenvPath)) {
        Write-Host "Creating virtual environment at $VenvPath ..."
        Invoke-CheckedCommand "create venv" { & $BasePython -m venv --copies $VenvPath }
    }

    $VenvPython = Join-Path $VenvPath "Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        throw "Venv python not found: $VenvPython"
    }

    $InstallFile = "requirements\workspace-default.lock"
    if ((-not $UseLock) -or (-not (Test-Path $InstallFile))) {
        $InstallFile = "requirements\workspace-default.txt"
    }
    if (-not (Test-Path $InstallFile)) {
        throw "Runtime requirements not found: $InstallFile"
    }

    $env:PYTHONNOUSERSITE = "1"
    Invoke-CheckedCommand "pip bootstrap" { & $VenvPython -m pip install --upgrade pip setuptools wheel }
    Invoke-CheckedCommand "runtime dependency install" { & $VenvPython -m pip install -r $InstallFile }
    Invoke-CheckedCommand "pip check" { & $VenvPython -m pip check }
    Invoke-CheckedCommand "core smoke" { & $VenvPython cli.py core smoke --profile framework-core --minimal-workspace }
    Invoke-CheckedCommand "compat check" { & $VenvPython cli.py compat check }

    New-Item -ItemType Directory -Force -Path "packages", "plans", "logs" | Out-Null
    Write-Host "Aura Runtime installed."
    Write-Host "Root       : $Root"
    Write-Host "Venv python: $VenvPython"
} finally {
    Pop-Location
}
