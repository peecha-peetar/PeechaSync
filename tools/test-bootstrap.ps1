param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [int]$TimeoutSec = 20
)

$ErrorActionPreference = 'Stop'
$out = Join-Path $env:TEMP 'peecha-bootstrap-test.txt'
Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue

if (-not (Test-Path -LiteralPath $PythonExe)) { exit 3 }
if (-not (Test-Path -LiteralPath $InstallDir)) { exit 4 }

$py = $PythonExe.Replace("'", "''")
$root = $InstallDir.TrimEnd('\').Replace("'", "''")

$code = @"
import os, sys
root = r'$root'
if root not in sys.path:
    sys.path.insert(0, root)
os.chdir(root)
os.environ['PYTHONPATH'] = root
from sync_app.core.peecha_launcher import main
print('OK bootstrap')
"@

$job = Start-Job -ScriptBlock {
    param($Py, $Snippet, $Log, $EnvRoot)
    $env:PYTHONPATH = $EnvRoot
    & $Py -c $Snippet *> $Log
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    exit 0
} -ArgumentList $PythonExe, $code, $out, $InstallDir.TrimEnd('\')

$done = Wait-Job -Job $job -Timeout $TimeoutSec
if (-not $done) {
    Stop-Job -Job $job -Force | Out-Null
    Remove-Job -Job $job -Force | Out-Null
    'TIMEOUT bootstrap test' | Set-Content -LiteralPath $out -Encoding UTF8
    exit 2
}

$rc = (Receive-Job -Job $job -ErrorAction SilentlyContinue)
Remove-Job -Job $job -Force | Out-Null
if (-not (Test-Path -LiteralPath $out)) {
    "no output (exit $rc)" | Set-Content -LiteralPath $out -Encoding UTF8
    exit 1
}
if ($rc -and $rc -ne 0) { exit [int]$rc }
exit 0
