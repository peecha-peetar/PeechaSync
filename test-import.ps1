param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [string]$Code = "import PyQt5, pyodbc, requests, woocommerce, cryptography, psutil; print('OK all imports')",
    [int]$TimeoutSec = 12
)

$ErrorActionPreference = 'Stop'
$out = Join-Path $env:TEMP 'peecha-import-test.txt'
Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue

$job = Start-Job -ScriptBlock {
    param($Py, $Snippet, $Log)
    & $Py -c $Snippet *> $Log
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    exit 0
} -ArgumentList $PythonExe, $Code, $out

$done = Wait-Job -Job $job -Timeout $TimeoutSec
if (-not $done) {
    Stop-Job -Job $job -Force | Out-Null
    Remove-Job -Job $job -Force | Out-Null
    'TIMEOUT import test' | Set-Content -LiteralPath $out -Encoding UTF8
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
