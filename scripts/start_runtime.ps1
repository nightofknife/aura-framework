param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 18098,
    [string]$VenvPython = ".venv\Scripts\python.exe",
    [string]$LogLevel = "info",
    [string]$RuntimeId = "default",
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $Root

try {
    if (-not (Test-Path $VenvPython)) {
        throw "Venv python not found: $VenvPython"
    }

    New-Item -ItemType Directory -Force -Path "logs" | Out-Null
    $TokenPath = Join-Path $Root "logs\local_api_token"
    if (-not (Test-Path $TokenPath)) {
        $bytes = New-Object byte[] 32
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $rng.GetBytes($bytes)
        } finally {
            $rng.Dispose()
        }
        [Convert]::ToBase64String($bytes) | Set-Content -Path $TokenPath -Encoding UTF8
    }

    & "$PSScriptRoot\register_runtime.ps1" -Id $RuntimeId -HostName $HostName -Port $Port -Status "running" -Version $Version -BasePath $Root

    $env:PYTHONNOUSERSITE = "1"
    $env:AURA_BASE_PATH = [string]$Root
    & $VenvPython cli.py api serve --host $HostName --port $Port --log-level $LogLevel
} finally {
    Pop-Location
}
