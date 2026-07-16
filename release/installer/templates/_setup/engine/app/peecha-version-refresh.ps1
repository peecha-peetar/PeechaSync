#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

$ErrorActionPreference = 'SilentlyContinue'
$root = $InstallRoot.TrimEnd('\', '/')
if (-not (Test-Path -LiteralPath $root)) { exit 0 }

$pycOnly = Test-Path -LiteralPath (Join-Path $root '.peecha-pyc-only')

$ver = ''
$verTxt = Join-Path $root 'VERSION.txt'
if (Test-Path -LiteralPath $verTxt) {
    $ver = (Get-Content -LiteralPath $verTxt -Raw -Encoding UTF8).Trim()
}
if (-not $ver) {
    $verPy = Join-Path $root 'sync_app\core\app_version.py'
    if (Test-Path -LiteralPath $verPy) {
        foreach ($line in Get-Content -LiteralPath $verPy -Encoding UTF8) {
            if ($line -match '_BUILTIN_VERSION\s*=\s*"([^"]+)"') {
                $ver = $Matches[1].Trim()
                break
            }
            if ($line -match 'APP_VERSION\s*=\s*"([^"]+)"') {
                $ver = $Matches[1].Trim()
                break
            }
        }
    }
}
if (-not $ver) {
    $py = Join-Path $root 'python\python.exe'
    if (-not (Test-Path -LiteralPath $py)) {
        $py = Join-Path $root '.venv\Scripts\python.exe'
    }
    if (Test-Path -LiteralPath $py) {
        $code = "import sys; sys.path.insert(0, r'$($root.Replace("'", "''"))'); from sync_app.core.app_version import APP_VERSION; print(APP_VERSION)"
        $out = & $py -c $code 2>$null
        if ($out) { $ver = [string]$out.Trim() }
    }
}
if (-not $ver) { exit 0 }

$stampFile = Join-Path $root '.peecha-installed-version'
$old = ''
if (Test-Path -LiteralPath $stampFile) {
    $old = (Get-Content -LiteralPath $stampFile -Raw -Encoding UTF8).Trim()
}
if ($ver -eq $old) { exit 0 }

if ($pycOnly) {
    Set-Content -LiteralPath $stampFile -Value $ver -Encoding UTF8 -NoNewline
    exit 0
}

$hasPy = Get-ChildItem -LiteralPath $root -Recurse -Filter '*.py' -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $hasPy) {
    Set-Content -LiteralPath $stampFile -Value $ver -Encoding UTF8 -NoNewline
    exit 0
}

$mainPyc = Join-Path $root 'main.pyc'
if (Test-Path -LiteralPath $mainPyc) {
    Remove-Item -LiteralPath $mainPyc -Force
}
Get-ChildItem -LiteralPath $root -Recurse -Directory -Filter '__pycache__' |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $root -Recurse -Filter '*.pyc' -File |
    Remove-Item -Force

$py = Join-Path $root 'python\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    $py = Join-Path $root '.venv\Scripts\python.exe'
}
if (Test-Path -LiteralPath $py) {
    & $py -m compileall -b -q $root 2>$null | Out-Null
    Get-ChildItem -LiteralPath $root -Recurse -Filter '*.py' -File -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

Set-Content -LiteralPath $stampFile -Value $ver -Encoding UTF8 -NoNewline
