#Requires -Version 5.1
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true)][string]$DestDir,
    [Parameter(Mandatory = $true)][string]$WheelsDir,
    [Parameter(Mandatory = $true)][string]$RequirementsFile
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-BuildPython {
    foreach ($cmd in @('py -3.12', 'py -3.11', 'python')) {
        $parts = $cmd.Split(' ')
        $exe = $parts[0]
        $args = @()
        if ($parts.Length -gt 1) { $args = $parts[1..($parts.Length - 1)] }
        $args += @('-c', 'import sys; assert sys.version_info[:2]>=(3,11)')
        try {
            & $exe @args 2>$null
            if ($LASTEXITCODE -eq 0) {
                return @{ Exe = $exe; Args = if ($parts.Length -gt 1) { $parts[1..($parts.Length - 1)] } else { @() } }
            }
        } catch {}
    }
    throw 'Python 3.11+ not found. Install from https://www.python.org/downloads/'
}

function Get-FindLinkDirs {
    $dirs = New-Object System.Collections.Generic.List[string]
    foreach ($rel in @(
        'release\installer\bootstrap-wheels',
        'release\installer\wheels'
    )) {
        $path = Join-Path $ProjectRoot $rel
        if ((Test-Path -LiteralPath $path) -and (Get-ChildItem -LiteralPath $path -Filter '*.whl' -File -ErrorAction SilentlyContinue)) {
            [void]$dirs.Add((Resolve-Path -LiteralPath $path).Path)
        }
    }
    if ((Test-Path -LiteralPath $WheelsDir) -and (Get-ChildItem -LiteralPath $WheelsDir -Filter '*.whl' -File -ErrorAction SilentlyContinue)) {
        $resolved = (Resolve-Path -LiteralPath $WheelsDir).Path
        if (-not $dirs.Contains($resolved)) { [void]$dirs.Add($resolved) }
    }
    return $dirs
}

function Invoke-EmbedPip {
    param(
        [string]$SiteDir,
        [string]$PyExe,
        [string[]]$PipArgs,
        [switch]$UseHostPip
    )
    if ($UseHostPip -or -not (Test-Path -LiteralPath $PyExe)) {
        $py = Get-BuildPython
        $args = @()
        if ($py.Args.Count -gt 0) { $args += $py.Args }
        $args += @('-m', 'pip', 'install', '--target', $SiteDir, '--no-index', '--no-warn-script-location', '--upgrade')
        foreach ($dir in (Get-FindLinkDirs)) {
            $args += @('--find-links', $dir)
        }
        $args += $PipArgs
        & $py.Exe @args
    } else {
        $args = @('-m', 'pip', 'install', '--no-index', '--no-warn-script-location', '--upgrade')
        foreach ($dir in (Get-FindLinkDirs)) {
            $args += @('--find-links', $dir)
        }
        $args += $PipArgs
        & $PyExe @args
    }
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed (exit $LASTEXITCODE): $($PipArgs -join ' ')"
    }
}

function Test-OtaWheelRejected {
    param([string]$WheelName)
    return $WheelName -match 'cp311-cp311'
}

function Find-OtaPackageWheel {
    param(
        [string]$WheelsDir,
        [string]$Package,
        [switch]$RequireCp312InName
    )
    $prefix = ($Package.ToLower() + '-')
    Get-ChildItem -LiteralPath $WheelsDir -Filter '*.whl' -ErrorAction SilentlyContinue |
        Where-Object {
            if ($_.PSIsContainer) { return $false }
            $n = $_.Name.ToLower()
            if (-not $n.StartsWith($prefix)) { return $false }
            if (Test-OtaWheelRejected $_.Name) { return $false }
            if ($RequireCp312InName -and $n -notmatch 'cp312') { return $false }
            return $true
        } | Select-Object -First 1
}

function Test-RequiredWheels {
    param([string]$WheelsDir)
    $need = @(
        @{ Package = 'PyQt5'; Cp312 = $false },
        @{ Package = 'pyodbc'; Cp312 = $true },
        @{ Package = 'cryptography'; Cp312 = $false },
        @{ Package = 'psutil'; Cp312 = $false }
    )
    foreach ($item in $need) {
        $hit = Find-OtaPackageWheel -WheelsDir $WheelsDir -Package $item.Package -RequireCp312InName:($item.Cp312)
        if (-not $hit) {
            throw "Missing wheel for $($item.Package) in $WheelsDir. Delete wheels folder and run release\download_install_wheels.ps1"
        }
    }
}

$pyVer = '3.12.10'
$cacheDir = Join-Path $ProjectRoot 'release\installer\python-embed-cache'
$zipPath = Join-Path $cacheDir "python-$pyVer-embed-amd64.zip"
$zipUrl = "https://www.python.org/ftp/python/$pyVer/python-$pyVer-embed-amd64.zip"

$findDirs = Get-FindLinkDirs
if ($findDirs.Count -lt 1) {
    throw 'No offline wheels found. Run release\download_install_wheels.ps1 once on a PC with internet, or copy release\installer\wheels\*.whl'
}
Test-RequiredWheels -WheelsDir $WheelsDir

New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $zipPath)) {
    Write-Host "Downloading Python $pyVer embed (one-time, needs internet) ..." -ForegroundColor DarkGray
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
    } catch {
        throw "Python embed ZIP missing and download failed. Copy python-$pyVer-embed-amd64.zip to $cacheDir"
    }
}

if (Test-Path -LiteralPath $DestDir) {
    Remove-Item -LiteralPath $DestDir -Recurse -Force
}
New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $DestDir -Force

$pthFile = Get-ChildItem -LiteralPath $DestDir -Filter '*._pth' -File | Select-Object -First 1
if (-not $pthFile) { throw 'python ._pth not found in embed package' }
$pthLines = @(Get-Content -LiteralPath $pthFile.FullName)
$pthOut = New-Object System.Collections.Generic.List[string]
$hasSite = $false
foreach ($line in $pthLines) {
    if ($line -match 'import site') {
        [void]$pthOut.Add('import site')
        $hasSite = $true
    } elseif ($line -notmatch '^\s*#\s*import site') {
        [void]$pthOut.Add($line)
    }
}
if (-not $hasSite) { [void]$pthOut.Add('import site') }
Set-Content -LiteralPath $pthFile.FullName -Value $pthOut -Encoding ASCII

$siteDir = Join-Path $DestDir 'Lib\site-packages'
New-Item -ItemType Directory -Path $siteDir -Force | Out-Null

Write-Host "Installing pip into embed Python (offline) ..." -ForegroundColor DarkGray
Invoke-EmbedPip -SiteDir $siteDir -PyExe '' -PipArgs @('pip', 'setuptools', 'wheel') -UseHostPip

$pyExe = Join-Path $DestDir 'python.exe'
Invoke-EmbedPip -SiteDir $siteDir -PyExe $pyExe -PipArgs @('-r', $RequirementsFile)

function Set-EmbedPythonw {
    param(
        [string]$PyExe,
        [string]$PywDest
    )
    if (Test-Path -LiteralPath $PywDest) {
        Remove-Item -LiteralPath $PywDest -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 300
    }
    Copy-Item -LiteralPath $PyExe -Destination $PywDest -Force
}

$pywDest = Join-Path $DestDir 'pythonw.exe'
Set-EmbedPythonw -PyExe $pyExe -PywDest $pywDest
Write-Host "pythonw: copy of embed python.exe (safe for offline install)" -ForegroundColor DarkGray

& $pyExe -c "import PyQt5, pyodbc, requests, woocommerce, cryptography, psutil"
if ($LASTEXITCODE -ne 0) { throw 'bundled python import check failed' }
& $pywDest -c "import PyQt5" 2>$null
if ($LASTEXITCODE -ne 0) { throw 'bundled pythonw import check failed' }

$sizeMb = [math]::Round(((Get-ChildItem -LiteralPath $DestDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host "Bundled Python: $DestDir ($sizeMb MB)" -ForegroundColor DarkGray
