param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000,
    [string]$VenvPython = ".venv\\Scripts\\python.exe",
    [string]$LogLevel = "info"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $VenvPython)) {
    throw "Venv python not found: $VenvPython"
}

$env:PYTHONNOUSERSITE = "1"
& $VenvPython cli.py api serve --host $Host --port $Port --log-level $LogLevel
