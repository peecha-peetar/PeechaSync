#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$DestRoot,
    [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'

function Write-SyncLog([string]$msg) {
    if (-not $LogPath) { return }
    Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] sync-packages-copy $msg" -Encoding UTF8
}

$src = $SourceRoot.TrimEnd('\', '/')
$dst = $DestRoot.TrimEnd('\', '/')
$wheels = @(Get-ChildItem -LiteralPath $src -Filter '*.whl' -File -ErrorAction SilentlyContinue)

if ($wheels.Count -lt 1) {
    Write-SyncLog 'no wheels - skip'
    exit 0
}

New-Item -ItemType Directory -Path $dst -Force | Out-Null
Write-SyncLog "copy $($wheels.Count) wheels -> $dst"
foreach ($whl in $wheels) {
    Copy-Item -LiteralPath $whl.FullName -Destination (Join-Path $dst $whl.Name) -Force
}

Write-SyncLog 'ok'
exit 0
