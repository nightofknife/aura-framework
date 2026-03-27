param(
    [string]$VenvPython = ".venv\\Scripts\\python.exe",
    [string]$LockFile = "requirements/runtime.lock"
)

$ErrorActionPreference = "Stop"

function Assert-PathExists {
    param([string]$PathValue, [string]$Label)
    if (-not (Test-Path $PathValue)) {
        throw "$Label not found: $PathValue"
    }
}

function Normalize-LockLines {
    param([string[]]$Lines)
    return $Lines `
        | ForEach-Object { $_.Trim() } `
        | Where-Object { $_ -and -not $_.StartsWith("#") } `
        | ForEach-Object { $_.ToLowerInvariant() } `
        | Sort-Object -Unique
}

Assert-PathExists -PathValue $VenvPython -Label "Venv python"
Assert-PathExists -PathValue $LockFile -Label "Lock file"

$venvVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
if (-not $venvVersion.StartsWith("3.13.")) {
    throw "Venv must be Python 3.13.x. Current: $venvVersion"
}

$pyvenvCfg = Join-Path (Split-Path (Split-Path $VenvPython -Parent) -Parent) "pyvenv.cfg"
Assert-PathExists -PathValue $pyvenvCfg -Label "pyvenv.cfg"
$cfgText = Get-Content $pyvenvCfg -Raw
if ($cfgText -notmatch "include-system-site-packages\s*=\s*false") {
    throw "Venv isolation check failed: include-system-site-packages must be false."
}

$env:PYTHONNOUSERSITE = "1"
$userSiteEnabled = & $VenvPython -c "import site; print('1' if site.ENABLE_USER_SITE else '0')"
if ($userSiteEnabled -ne "0") {
    throw "User site packages are enabled. Expected disabled."
}

Write-Host "Validating lock consistency ..."
$freezeLines = & $VenvPython -m pip freeze --all
$lockLines = Get-Content $LockFile

$freezeNorm = Normalize-LockLines -Lines $freezeLines
$lockNorm = Normalize-LockLines -Lines $lockLines

$diff = Compare-Object -ReferenceObject $lockNorm -DifferenceObject $freezeNorm
if ($diff) {
    $preview = $diff | Select-Object -First 20 | Out-String
    throw "Installed packages do not match lock file.`n$preview"
}

Write-Host "Running pip check ..."
& $VenvPython -m pip check

Write-Host "Running startup smoke checks ..."
& $VenvPython cli.py --help | Out-Null
& $VenvPython -c "import backend.run" | Out-Null

& $VenvPython -c @"
from fastapi.testclient import TestClient
from backend.api.app import create_app

app = create_app()
with TestClient(app) as c:
    r = c.get('/api/v1/system/health')
    assert r.status_code == 200
"@ | Out-Null

Write-Host "Preflight passed."
