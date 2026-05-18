param(
    [string]$BasePython = "C:\\Python313\\python.exe",
    [string]$VenvPath = ".venv-test",
    [switch]$IncludeYolo
)

$ErrorActionPreference = "Stop"

$profiles = @("workspace-default", "test")
if ($IncludeYolo) {
    $profiles += "yolo"
}

$setupScript = Join-Path $PSScriptRoot "setup_python_runtime.ps1"
if (-not (Test-Path $setupScript)) {
    throw "Setup script not found: $setupScript"
}

& $setupScript -BasePython $BasePython -VenvPath $VenvPath -Profiles $profiles
