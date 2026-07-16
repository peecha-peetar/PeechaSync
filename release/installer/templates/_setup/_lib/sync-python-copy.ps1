#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$DestRoot,
    [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'

function Write-SyncLog([string]$msg) {
    if (-not $LogPath) { return }
    Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] sync-python-copy $msg" -Encoding UTF8
}

$src = $SourceRoot.TrimEnd('\', '/')
$dst = $DestRoot.TrimEnd('\', '/')
$srcExe = Join-Path $src 'python.exe'

if (-not (Test-Path -LiteralPath $srcExe)) {
    throw "python.exe missing in source: $srcExe"
}

Get-Process python, pythonw -ErrorAction SilentlyContinue | ForEach-Object {
    $p = $_.Path
    $c = ''
    try { $c = $_.CommandLine } catch {}
    if (($p -and $p -like '*PeechaSync*') -or ($c -and ($c -like '*PeechaSync*' -or $c -like '*main.pyc*'))) {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

if (Test-Path -LiteralPath $dst) {
    Write-SyncLog "remove old $dst"
    Remove-Item -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 5; $i++) {
        if (-not (Test-Path -LiteralPath $dst)) { break }
        Start-Sleep -Seconds 2
        Remove-Item -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$parent = Split-Path -Path $dst -Parent
if (-not $parent) { throw "invalid destination: $dst" }

Write-SyncLog "copy $src -> $dst"
Copy-Item -LiteralPath $src -Destination $parent -Recurse -Force

if (-not (Test-Path -LiteralPath (Join-Path $dst 'python.exe'))) {
    throw 'python copy incomplete (python.exe missing)'
}

Write-SyncLog 'ok'
exit 0
