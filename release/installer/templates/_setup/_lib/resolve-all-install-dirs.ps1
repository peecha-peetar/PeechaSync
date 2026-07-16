#Requires -Version 5.1
param(
    [string[]]$ExtraPaths = @()
)

$ErrorActionPreference = 'SilentlyContinue'
$dirs = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$found = New-Object System.Collections.Generic.List[string]

foreach ($p in @('C:\PeechaSync', 'D:\PeechaSync', 'E:\PeechaSync')) {
    [void]$dirs.Add($p)
}
foreach ($p in $ExtraPaths) {
    $t = ($p | Out-String).Trim()
    if ($t) { [void]$dirs.Add($t) }
}

$loc = Join-Path $env:LOCALAPPDATA 'PeechaSync\install.loc'
if (Test-Path -LiteralPath $loc) {
    $raw = (Get-Content -LiteralPath $loc -Raw).Trim().TrimStart([char]0xFEFF)
    if ($raw) { [void]$dirs.Add($raw) }
}

foreach ($key in @('Desktop', 'CommonDesktop')) {
    try {
        $desktop = [Environment]::GetFolderPath($key)
        if (-not $desktop) { continue }
        $lnk = Join-Path $desktop 'PeechaSync.lnk'
        if (-not (Test-Path -LiteralPath $lnk)) { continue }
        $sh = New-Object -ComObject WScript.Shell
        $target = $sh.CreateShortcut($lnk).TargetPath
        if ($target) {
            $parent = Split-Path -Parent $target
            if ($parent) { [void]$dirs.Add($parent) }
        }
    } catch {}
}

foreach ($d in $dirs) {
    if (-not $d) { continue }
    if (-not (Test-Path -LiteralPath $d)) { continue }
    $runner = Join-Path $d 'Run-PeechaSync.bat'
    $mainPyc = Join-Path $d 'main.pyc'
    $syncApp = Join-Path $d 'sync_app'
    if ((Test-Path -LiteralPath $runner) -or (Test-Path -LiteralPath $mainPyc) -or (Test-Path -LiteralPath $syncApp)) {
        [void]$found.Add($d)
    }
}

$found | Sort-Object -Unique
