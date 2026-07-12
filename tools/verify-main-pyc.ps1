param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$MainPyc,
    [string]$InstallDir = '',
    [string]$LogFile = '',
    [int]$TimeoutSec = 15
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $PythonExe)) { exit 3 }
if (-not (Test-Path -LiteralPath $MainPyc)) { exit 4 }

if (-not $InstallDir) {
    $InstallDir = Split-Path -Parent $MainPyc
}

$out = if ($LogFile) { $LogFile } else { Join-Path $env:TEMP 'peecha-main-pyc-test.txt' }
Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue

$py = $PythonExe.Replace("'", "''")
$main = $MainPyc.Replace("'", "''")
$root = $InstallDir.Replace("'", "''")

$code = @"
import marshal, os, sys
root = r'$root'
main = r'$main'
with open(main, 'rb') as f:
    f.read(16)
    marshal.loads(f.read())
if root not in sys.path:
    sys.path.insert(0, root)
os.chdir(root)
os.environ['PYTHONPATH'] = root
from sync_app.core.peecha_launcher import main as _peecha_main
print('main.pyc ok')
"@

$job = Start-Job -ScriptBlock {
    param($Py, $Snippet, $Log)
    & $Py -c $Snippet *> $Log
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    exit 0
} -ArgumentList $PythonExe, $code, $out

$done = Wait-Job -Job $job -Timeout $TimeoutSec
if (-not $done) {
    Stop-Job -Job $job -Force | Out-Null
    Remove-Job -Job $job -Force | Out-Null
    'TIMEOUT main.pyc test' | Set-Content -LiteralPath $out -Encoding UTF8
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
