param(
    [string]$Id = "default",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 18098,
    [string]$Status = "running",
    [string]$Version = "0.1.0",
    [string]$BasePath = ""
)

$ErrorActionPreference = "Stop"

if (-not $BasePath) {
    $BasePath = Resolve-Path (Join-Path $PSScriptRoot "..")
} else {
    $BasePath = Resolve-Path $BasePath
}

$RegistryDir = Join-Path $env:LOCALAPPDATA "Aura"
$RegistryPath = Join-Path $RegistryDir "runtime-registry.json"
$ApiBase = "http://${HostName}:${Port}/api/v1"
$WsBase = "ws://${HostName}:${Port}"
$TokenPath = Join-Path $BasePath "logs\local_api_token"

New-Item -ItemType Directory -Force -Path $RegistryDir | Out-Null

$Instances = @()
if (Test-Path $RegistryPath) {
    try {
        $Parsed = Get-Content $RegistryPath -Raw | ConvertFrom-Json
        if ($Parsed.instances) {
            $Instances = @($Parsed.instances)
        }
    } catch {
        $Instances = @()
    }
}

$Entry = [ordered]@{
    id = $Id
    version = $Version
    host = $HostName
    port = $Port
    info_port = $Port
    base_path = [string]$BasePath
    api_base = $ApiBase
    ws_base = $WsBase
    token_path = $TokenPath
    status = $Status
}

$Instances = @($Instances | Where-Object {
    $_.id -ne $Id -and $_.api_base -ne $ApiBase -and $_.base_path -ne [string]$BasePath
})
$Registry = [ordered]@{ instances = @($Entry) + $Instances }
$Registry | ConvertTo-Json -Depth 8 | Set-Content -Path $RegistryPath -Encoding UTF8

Write-Host "Aura runtime registered: $RegistryPath"
Write-Host "API: $ApiBase"
