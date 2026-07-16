#Requires -Version 5.1
param(
    [string[]]$InstallDirs = @(),
    [int]$WaitSeconds = 3
)

$ErrorActionPreference = 'SilentlyContinue'

function Get-TargetInstallDirs {
    $set = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($p in $InstallDirs) {
        $t = ($p | Out-String).Trim().TrimStart([char]0xFEFF)
        if ($t) { [void]$set.Add($t.TrimEnd('\', '/')) }
    }
    foreach ($p in @('C:\PeechaSync', 'D:\PeechaSync')) {
        [void]$set.Add($p)
    }
    $loc = Join-Path $env:LOCALAPPDATA 'PeechaSync\install.loc'
    if (Test-Path -LiteralPath $loc) {
        $raw = (Get-Content -LiteralPath $loc -Raw).Trim().TrimStart([char]0xFEFF)
        if ($raw) { [void]$set.Add($raw.TrimEnd('\', '/')) }
    }
  return @($set)
}

function Stop-ProcessSafe([int]$pid) {
    if ($pid -le 0) { return }
    try { Stop-Process -Id $pid -Force -ErrorAction Stop } catch {}
    try { taskkill /F /PID $pid /T 2>$null | Out-Null } catch {}
}

function Stop-PeechaByCommandLine {
    param([string]$commandLine)
    if (-not $commandLine) { return $false }
    $cl = $commandLine
    return (
        $cl -like '*PeechaSync*' -or
        $cl -like '*main.pyc*' -or
        $cl -like '*main.py*' -or
        $cl -like '*peecha*' -or
        $cl -like '*Launch-PeechaSync*'
    )
}

$dirs = Get-TargetInstallDirs

foreach ($round in 1..3) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -in @('wscript.exe', 'cscript.exe') -and (Stop-PeechaByCommandLine $_.CommandLine)
        } |
        ForEach-Object { Stop-ProcessSafe $_.ProcessId }

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -in @('python.exe', 'pythonw.exe', 'py.exe') -and (Stop-PeechaByCommandLine $_.CommandLine)
        } |
        ForEach-Object { Stop-ProcessSafe $_.ProcessId }

    foreach ($dir in $dirs) {
        if (-not $dir) { continue }
        $pyRoot = Join-Path $dir 'python'
        Get-Process -Name python, pythonw, py -ErrorAction SilentlyContinue | ForEach-Object {
            $path = $_.Path
            if ($path -and ($path -like "$pyRoot*" -or $path -like "$dir*")) {
                Stop-ProcessSafe $_.Id
            }
        }
    }

    if ($round -lt 3) { Start-Sleep -Seconds 1 }
}

taskkill /F /IM pythonw.exe /T 2>$null | Out-Null
foreach ($dir in $dirs) {
    if (-not $dir) { continue }
    $pyExe = Join-Path $dir 'python\python.exe'
    if (-not (Test-Path -LiteralPath $pyExe)) { continue }
    Get-Process -Name python, pythonw -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            if ($_.Path -and ($_.Path -eq $pyExe -or $_.Path -like "$(Split-Path -Parent $pyExe)\*")) {
                Stop-ProcessSafe $_.Id
            }
        } catch {}
    }
}

if ($WaitSeconds -gt 0) { Start-Sleep -Seconds $WaitSeconds }
exit 0
