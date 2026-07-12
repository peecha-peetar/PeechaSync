#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$DestRoot,
    [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'

function Write-SyncLog([string]$msg) {
    if (-not $LogPath) { return }
    Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] sync-app-copy $msg" -Encoding UTF8
}

$src = $SourceRoot.TrimEnd('\', '/')
$dst = $DestRoot.TrimEnd('\', '/')
$srcSync = Join-Path $src 'sync_app'
$dstSync = Join-Path $dst 'sync_app'

if (-not (Test-Path -LiteralPath $srcSync)) {
    throw "sync_app missing in source: $srcSync"
}

New-Item -ItemType Directory -Path $dst -Force | Out-Null

Get-Process python, pythonw -ErrorAction SilentlyContinue | ForEach-Object {
    $p = $_.Path
    $c = ''
    try { $c = $_.CommandLine } catch {}
    if (($p -and $p -like '*PeechaSync*') -or ($c -and ($c -like '*PeechaSync*' -or $c -like '*main.pyc*'))) {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

if (Test-Path -LiteralPath $dstSync) {
    Write-SyncLog "remove old $dstSync"
    Remove-Item -LiteralPath $dstSync -Recurse -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 5; $i++) {
        if (-not (Test-Path -LiteralPath $dstSync)) { break }
        Start-Sleep -Seconds 2
        Remove-Item -LiteralPath $dstSync -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-SyncLog "copy $srcSync -> $dstSync"
Copy-Item -LiteralPath $srcSync -Destination $dstSync -Recurse -Force

$pycCount = @(Get-ChildItem -LiteralPath $dstSync -Recurse -Filter '*.pyc' -File -ErrorAction SilentlyContinue).Count
if ($pycCount -lt 10) {
    throw "sync_app copy incomplete ($pycCount .pyc files)"
}

$rootFiles = @(
    'main.pyc', 'main.py', 'requirements.txt', 'PeechaSync.ico', 'VERSION.txt',
    'Run-PeechaSync.bat', 'Launch-PeechaSync.vbs', 'launch-gui.cmd', 'launch-gui.ps1',
    'patch-launch-env.cmd', 'repair-launch-env.cmd', 'set-python-env.bat',
    'test-import.ps1', 'test-bootstrap.ps1', 'verify-main-pyc.ps1',
    'show-startup-error.bat', 'show-user-message.ps1', 'check-internet.bat',
    'peecha-version-refresh.ps1', 'Apply-ClientUpdate.ps1', 'Force-CleanProgramFiles.ps1',
    'Assert-InstalledVersion.ps1', 'peecha-apply-cached-update.ps1', 'Apply-CachedUpdate.bat',
    'kill-peecha-processes.ps1', '.peecha-pyc-only', '.peecha-release'
)
foreach ($name in $rootFiles) {
    $from = Join-Path $src $name
    if (Test-Path -LiteralPath $from) {
        Copy-Item -LiteralPath $from -Destination (Join-Path $dst $name) -Force
    }
}

Write-SyncLog 'ok'
exit 0
