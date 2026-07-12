#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedVersion
)

$ErrorActionPreference = 'Stop'
$root = $InstallRoot.TrimEnd('\', '/')
$verFile = Join-Path $root 'VERSION.txt'
if (-not (Test-Path -LiteralPath $verFile)) {
    throw "VERSION.txt missing after install: $verFile"
}
$installed = (Get-Content -LiteralPath $verFile -Raw -Encoding UTF8).Trim()
if ($installed -ne $ExpectedVersion) {
    throw "Installed version '$installed' != expected '$ExpectedVersion'"
}

$py = Join-Path $root 'python\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    $py = Join-Path $root '.venv\Scripts\python.exe'
}
if (Test-Path -LiteralPath $py) {
    $code = @"
import sys
sys.path.insert(0, r'$($root.Replace("'", "''"))')
from sync_app.core.app_version import APP_VERSION
print(APP_VERSION)
"@
    $runtime = (& $py -c $code 2>$null | Out-String).Trim()
    if ($runtime -and $runtime -ne $ExpectedVersion) {
        throw "Runtime APP_VERSION '$runtime' != expected '$ExpectedVersion'"
    }
}

Write-Host "Version OK: $ExpectedVersion" -ForegroundColor Green
