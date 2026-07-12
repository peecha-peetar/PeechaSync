#Requires -Version 5.1
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

function Get-DownloadPython {
    foreach ($cmd in @('py -3.12', 'py -3.11', 'python3', 'python')) {
        $parts = $cmd.Split(' ')
        $exe = $parts[0]
        $args = @()
        if ($parts.Length -gt 1) { $args = $parts[1..($parts.Length - 1)] }
        $args += @('-m', 'pip', '--version')
        try {
            & $exe @args 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return @{ Exe = $exe; Args = if ($parts.Length -gt 1) { $parts[1..($parts.Length - 1)] } else { @() } }
            }
        } catch {}
    }
    throw 'pip not found. Install Python 3.11+ from https://www.python.org/downloads/'
}

$req = Join-Path $ProjectRoot 'release\requirements-client.txt'
$dest = Join-Path $ProjectRoot 'release\installer\wheels'
if (-not (Test-Path -LiteralPath $req)) {
    throw "Requirements not found: $req"
}
New-Item -ItemType Directory -Path $dest -Force | Out-Null

$embedPyVer = '312'
$py = Get-DownloadPython
Write-Host "Downloading Windows wheels (cp$embedPyVer) to $dest ..." -ForegroundColor Cyan

$dlArgs = @()
if ($py.Args.Count -gt 0) { $dlArgs += $py.Args }
$dlArgs += @(
    '-m', 'pip', 'download',
    '-r', $req,
    '-d', $dest,
    '--platform', 'win_amd64',
    '--python-version', $embedPyVer,
    '--implementation', 'cp',
    '--only-binary', ':all:'
)
& $py.Exe @dlArgs
if ($LASTEXITCODE -ne 0) {
    throw "pip download failed for cp$embedPyVer (exit $LASTEXITCODE)"
}

$count = (Get-ChildItem -LiteralPath $dest -Filter '*.whl' -File).Count
$sizeMb = [math]::Round(((Get-ChildItem -LiteralPath $dest -Filter '*.whl' -File | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host "OK: $count wheels ($sizeMb MB)" -ForegroundColor Green
