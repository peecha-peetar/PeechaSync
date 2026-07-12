#Requires -Version 5.1
$ErrorActionPreference = 'Continue'
$lib = $PSScriptRoot
$target = 'C:\PeechaSync'
$progress = Join-Path $env:LOCALAPPDATA 'PeechaSync\install-progress.txt'
$log = Join-Path $env:LOCALAPPDATA 'PeechaSync\install-errors.log'

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ' PeechaSync Install (live log)' -ForegroundColor Cyan
Write-Host " Target: $target" -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''

& (Join-Path $lib 'kill-peecha-processes.bat') | Out-Null

if (Test-Path -LiteralPath $progress) { Remove-Item -LiteralPath $progress -Force -ErrorAction SilentlyContinue }

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'cmd.exe'
$psi.Arguments = '/c install-app.bat'
$psi.WorkingDirectory = $lib
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$proc = [System.Diagnostics.Process]::Start($psi)

$lastStep = ''
$map = @{
    'starting'      = '1/6 Start'
    'clean-old'     = '2/6 Remove old files'
    'copy-app'      = '3/6 Copy program files'
    'copy-packages' = '4/6 Copy packages'
    'copy-python'   = '5/6 Copy Python (slow)'
    'deps'          = '5/6 Install packages'
    'repair-launch' = '6/6 Finish launcher'
    'finalize'      = '6/6 Finalize'
    'done'          = 'Done'
}

while (-not $proc.HasExited) {
    if (Test-Path -LiteralPath $progress) {
        $step = (Get-Content -LiteralPath $progress -Tail 1 -ErrorAction SilentlyContinue).Trim()
        if ($step -and $step -ne $lastStep) {
            $label = if ($map.ContainsKey($step)) { $map[$step] } else { $step }
            Write-Host "  >> $label" -ForegroundColor Green
            $lastStep = $step
        }
    }
    Start-Sleep -Milliseconds 400
}

$rc = $proc.ExitCode
Write-Host ''
if ($rc -eq 0) {
    Write-Host 'SUCCESS - install finished.' -ForegroundColor Green
    if (Test-Path -LiteralPath (Join-Path $target 'VERSION.txt')) {
        $v = (Get-Content -LiteralPath (Join-Path $target 'VERSION.txt') -Raw).Trim()
        Write-Host "Version: $v"
    }
    if (Test-Path -LiteralPath (Join-Path $target 'sync_app\core\peecha_launcher.pyc')) {
        Write-Host 'sync_app: OK'
    } else {
        Write-Host 'WARN: sync_app missing!' -ForegroundColor Yellow
        $rc = 1
    }
} else {
    Write-Host "FAILED - exit code $rc" -ForegroundColor Red
    if (Test-Path -LiteralPath $log) {
        Write-Host ''
        Write-Host '--- install-errors.log (last 20 lines) ---' -ForegroundColor Yellow
        Get-Content -LiteralPath $log -Tail 20 | ForEach-Object { Write-Host $_ }
    }
}

exit $rc
