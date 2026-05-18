param(
    [string]$BasePython = "C:\\Python313\\python.exe",
    [string]$VenvPath = ".venv",
    [string[]]$Profiles = @("workspace-default"),
    [switch]$UseLock = $true
)

$ErrorActionPreference = "Stop"

$profileMap = @{
    "framework-core"    = @{ Requirements = "requirements/framework-core.txt"; Lock = $null }
    "workspace-default" = @{ Requirements = "requirements/workspace-default.txt"; Lock = "requirements/workspace-default.lock" }
    "yolo"              = @{ Requirements = "requirements/yolo.txt"; Lock = $null }
    "test"              = @{ Requirements = "requirements/test.txt"; Lock = $null }
}

function Assert-PathExists {
    param([string]$PathValue, [string]$Label)
    if (-not (Test-Path $PathValue)) {
        throw "$Label not found: $PathValue"
    }
}

function Get-InstallFileForProfile {
    param([string]$ProfileName, [bool]$PreferLock)

    if (-not $profileMap.ContainsKey($ProfileName)) {
        throw "Unknown dependency profile: $ProfileName"
    }

    $spec = $profileMap[$ProfileName]
    $requirementsFile = [string]$spec.Requirements
    Assert-PathExists -PathValue $requirementsFile -Label "$ProfileName requirements"

    $lockFile = [string]$spec.Lock
    if ($PreferLock -and $lockFile -and (Test-Path $lockFile)) {
        return $lockFile
    }
    return $requirementsFile
}

Assert-PathExists -PathValue $BasePython -Label "Base Python"
foreach ($profile in $Profiles) {
    [void](Get-InstallFileForProfile -ProfileName $profile -PreferLock:$UseLock)
}

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

foreach ($profile in $Profiles) {
    $installFile = Get-InstallFileForProfile -ProfileName $profile -PreferLock:$UseLock
    Write-Host "Installing profile '$profile' from $installFile ..."
    & $venvPython -m pip install -r $installFile
}

if (-not $UseLock -and $Profiles.Count -eq 1 -and $Profiles[0] -eq "workspace-default") {
    & $venvPython -m pip freeze --all | Set-Content -Path "requirements/workspace-default.lock" -Encoding UTF8
}

Write-Host "Running pip check ..."
& $venvPython -m pip check

$venvVersion = & $venvPython -c "import sys; print(sys.version)"
Write-Host ""
Write-Host "Runtime ready."
Write-Host "Base python : $BasePython"
Write-Host "Venv python : $venvPython"
Write-Host "Profiles    : $($Profiles -join ', ')"
Write-Host "Version     : $venvVersion"
