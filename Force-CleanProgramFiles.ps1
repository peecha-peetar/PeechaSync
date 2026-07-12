#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'
$root = $InstallRoot.TrimEnd('\', '/')
if (-not (Test-Path -LiteralPath $root)) {
    return
}

function Write-CleanLog([string]$msg) {
    if (-not $LogPath) { return }
    Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] force-clean $msg" -Encoding UTF8
}

Write-CleanLog "start install=$root"
Write-Host "Force clean program files: $root" -ForegroundColor DarkGray
Write-Host "Keeping: license, settings, maps, images (not SQL)" -ForegroundColor DarkGray

Get-Process pythonw, python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and ($_.Path -like "*PeechaSync*")
} | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

function Remove-TreeRetry([string]$path, [int]$attempts = 5) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    for ($i = 0; $i -lt $attempts; $i++) {
        try {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
            if (-not (Test-Path -LiteralPath $path)) { return }
        } catch {
            Get-Process pythonw, python -ErrorAction SilentlyContinue | Where-Object {
                $_.Path -and ($_.Path -like "*PeechaSync*")
            } | ForEach-Object {
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds (2 + $i)
        }
    }
    if (Test-Path -LiteralPath $path) {
        Write-CleanLog "WARN could not remove $path (files may be locked)"
    }
}

foreach ($dir in @('sync_app', 'python', '_packages', 'release', 'tools')) {
    $path = Join-Path $root $dir
    if (Test-Path -LiteralPath $path) {
        Write-CleanLog "remove $dir"
        Remove-TreeRetry $path
    }
}

foreach ($name in @(
        'main.py', 'main.pyc', 'requirements.txt', 'PeechaSync.ico', 'VERSION.txt',
        'Run-PeechaSync.bat', 'Launch-PeechaSync.vbs', 'launch-gui.cmd', 'launch-gui.ps1',
        'patch-launch-env.cmd', 'repair-launch-env.cmd', 'set-python-env.bat',
        'test-import.ps1', 'test-bootstrap.ps1', 'verify-main-pyc.ps1',
        'show-startup-error.bat', 'show-user-message.ps1', 'check-internet.bat',
        'peecha-version-refresh.ps1', 'Apply-ClientUpdate.ps1', 'Force-CleanProgramFiles.ps1',
        'Assert-InstalledVersion.ps1', 'peecha-apply-cached-update.ps1', 'Apply-CachedUpdate.bat',
        '.peecha-pyc-only', '.peecha-release', '.peecha-installed-version'
    )) {
    $path = Join-Path $root $name
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

Get-ChildItem -LiteralPath $root -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $root -Recurse -Filter '*.pyc' -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath (Join-Path $root '__pycache__')) {
    Remove-Item -LiteralPath (Join-Path $root '__pycache__') -Recurse -Force -ErrorAction SilentlyContinue
}

Write-CleanLog 'done'
Write-Host "Force clean done." -ForegroundColor DarkGray
