param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 18098,
    [string]$VenvPath = ".venv",
    [string]$BasePython = "C:\Python313\python.exe",
    [string]$LogLevel = "info",
    [string]$RuntimeId = "default",
    [string]$Version = "0.1.0",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

Push-Location $Root
try {
    Write-Host "Aura Runtime"
    Write-Host "Root       : $Root"
    Write-Host "API        : http://${HostName}:${Port}/api/v1"
    Write-Host "Registry   : %LOCALAPPDATA%\Aura\runtime-registry.json"
    Write-Host ""

    if (-not (Test-Path $VenvPython)) {
        if ($SkipInstall) {
            throw "Venv python not found: $VenvPython"
        }
        Write-Host "Runtime environment is not installed. Installing first..."
        & "$PSScriptRoot\install_runtime.ps1" -BasePython $BasePython -VenvPath $VenvPath
        if ($LASTEXITCODE -ne 0) {
            throw "install_runtime.ps1 failed with exit code $LASTEXITCODE"
        }
        Write-Host ""
    }

    Write-Host "Starting Aura Runtime on ${HostName}:${Port} ..."
    Write-Host "Keep this window open while using Aura GUI."
    Write-Host ""

    & "$PSScriptRoot\start_runtime.ps1" `
        -HostName $HostName `
        -Port $Port `
        -VenvPython $VenvPython `
        -LogLevel $LogLevel `
        -RuntimeId $RuntimeId `
        -Version $Version
    if ($LASTEXITCODE -ne 0) {
        throw "start_runtime.ps1 failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
