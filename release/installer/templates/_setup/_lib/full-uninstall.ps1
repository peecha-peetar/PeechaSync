#Requires -Version 5.1
param(
    [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'
$lib = $PSScriptRoot
. (Join-Path $lib 'install-markers.ps1')

function Write-UninstallLog([string]$msg) {
    if (-not $LogPath) { return }
    Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" -Encoding UTF8
}

function Stop-PeechaProcesses {
    Write-UninstallLog 'kill processes'
    $installDirs = @(& (Join-Path $lib 'resolve-all-install-dirs.ps1'))
    if ($installDirs.Count -lt 1) {
        $installDirs = @('C:\PeechaSync', 'D:\PeechaSync')
    }
    & (Join-Path $lib 'kill-peecha-processes.ps1') -InstallDirs $installDirs -WaitSeconds 3 | Out-Null
}

$installDirs = @(& (Join-Path $lib 'resolve-all-install-dirs.ps1'))
if ($installDirs.Count -lt 1) {
    foreach ($p in @('C:\PeechaSync', 'D:\PeechaSync')) {
        if (Test-PeechaProgramInstalled $p) { $installDirs += $p }
    }
}
Write-UninstallLog ("install dirs: " + ($installDirs -join '; '))

Stop-PeechaProcesses

$cleanPs = Join-Path $lib '..\engine\app\Force-CleanProgramFiles.ps1'
if (-not (Test-Path -LiteralPath $cleanPs)) {
    throw "Force-CleanProgramFiles.ps1 not found: $cleanPs"
}

$cleaned = 0
foreach ($dir in ($installDirs | Sort-Object -Unique)) {
    if (-not (Test-PeechaProgramInstalled $dir)) { continue }
    Write-UninstallLog "clean $dir"
    & $cleanPs -InstallRoot $dir -LogPath $LogPath
    Start-Sleep -Seconds 1
    if (Test-PeechaProgramInstalled $dir) {
        Stop-PeechaProcesses
        & $cleanPs -InstallRoot $dir -LogPath $LogPath
        Start-Sleep -Seconds 2
    }
    if (Test-PeechaProgramInstalled $dir) {
        Write-UninstallLog "WARN program files remain in $dir after clean"
        throw "Could not remove PeechaSync program files in $dir. Close PeechaSync from the taskbar and try again."
    }
    $cleaned++
}

if ($cleaned -eq 0) {
    Write-UninstallLog 'no PeechaSync program files found to remove'
}

& (Join-Path $lib 'remove-shortcuts.ps1') | Out-Null

$stateRoot = Join-Path $env:LOCALAPPDATA 'PeechaSync'
foreach ($name in @('install.loc', 'pending-update.json', 'update-apply-failed.json', 'install-progress.txt', 'update-apply-attempts.json')) {
    $p = Join-Path $stateRoot $name
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
}

$cacheDir = Join-Path $env:TEMP 'PeechaSync-updates'
if (Test-Path -LiteralPath $cacheDir) {
    Remove-Item -LiteralPath $cacheDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-UninstallLog 'done'
exit 0
