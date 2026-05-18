param(
    [string]$VenvPython = ".venv-test\\Scripts\\python.exe",
    [switch]$IncludeYolo
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $VenvPython)) {
    throw "Venv python not found: $VenvPython"
}

$markers = @("not slow")
if (-not $IncludeYolo) {
    $markers += "not yolo"
}

$expr = $markers -join " and "
$env:PYTHONNOUSERSITE = "1"
& $VenvPython -m pytest -m $expr
