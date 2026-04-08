param(
    [string]$BasePython = "C:\\Python313\\python.exe",
    [string]$VenvPath = ".venv",
    [string]$RuntimeRequirements = "requirements/runtime.txt",
    [string]$LockFile = "requirements/runtime.lock",
    [switch]$UseLock = $true
)

$ErrorActionPreference = "Stop"

function Assert-PathExists {
    param([string]$PathValue, [string]$Label)
    if (-not (Test-Path $PathValue)) {
        throw "$Label not found: $PathValue"
    }
}

Assert-PathExists -PathValue $BasePython -Label "Base Python"
Assert-PathExists -PathValue $RuntimeRequirements -Label "Runtime requirements"

$version = & $BasePython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
if (-not $version.StartsWith("3.13.")) {
    throw "Base Python must be 3.13.x. Current: $version"
}

if (-not (Test-Path $VenvPath)) {
    Write-Host "Creating virtual environment at $VenvPath using $BasePython ..."
    & $BasePython -m venv --copies $VenvPath
}

$venvPython = Join-Path $VenvPath "Scripts/python.exe"
Assert-PathExists -PathValue $venvPython -Label "Venv python"

$pyvenvCfg = Join-Path $VenvPath "pyvenv.cfg"
Assert-PathExists -PathValue $pyvenvCfg -Label "pyvenv.cfg"

$cfgText = Get-Content $pyvenvCfg -Raw
if ($cfgText -notmatch "include-system-site-packages\s*=\s*false") {
    $cfgText = [regex]::Replace(
        $cfgText,
        "include-system-site-packages\s*=\s*true",
        "include-system-site-packages = false"
    )
    Set-Content -Path $pyvenvCfg -Value $cfgText -Encoding UTF8
}

Write-Host "Installing runtime dependencies ..."
& $venvPython -m pip install --upgrade pip setuptools wheel

if ($UseLock -and (Test-Path $LockFile)) {
    & $venvPython -m pip install -r $LockFile
} else {
    & $venvPython -m pip install -r $RuntimeRequirements
    & $venvPython -m pip freeze --all | Set-Content -Path $LockFile -Encoding UTF8
}

Write-Host "Running pip check ..."
& $venvPython -m pip check

$venvVersion = & $venvPython -c "import sys; print(sys.version)"
Write-Host ""
Write-Host "Runtime ready."
Write-Host "Base python : $BasePython"
Write-Host "Venv python : $venvPython"
Write-Host "Version     : $venvVersion"
