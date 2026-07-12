#Requires -Version 5.1
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

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

function Copy-TreeFiltered {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$SkipNames = @()
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Source not found: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        if ($SkipNames -contains $item.Name) { continue }
        $target = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) {
            Copy-TreeFiltered -Source $item.FullName -Destination $target -SkipNames $SkipNames
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

function Ensure-InstallWheels {
    param([string]$ProjectRoot, [string]$DestDir)

    . (Join-Path $ProjectRoot 'tools\ClientRelease-Common.ps1')
    $wheelsSrc = [string](Ensure-ClientWheels -ProjectRoot $ProjectRoot)
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    $wheelFiles = @(Get-ChildItem -LiteralPath $wheelsSrc -Filter '*.whl' -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer -and $_.Name -notmatch 'cp311-cp311' })
    foreach ($whl in $wheelFiles) {
        Copy-Item -LiteralPath $whl.FullName -Destination (Join-Path $DestDir $whl.Name) -Force
    }
    if ($wheelFiles.Count -lt 1) {
        throw "No wheels copied to $DestDir"
    }
    $sizeMb = [math]::Round((($wheelFiles | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
    Write-Host "Offline packages: $($wheelFiles.Count) wheels ($sizeMb MB)" -ForegroundColor DarkGray
}

function Hide-PackageDir {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    $item.Attributes = $item.Attributes -bor [IO.FileAttributes]::Hidden
}

function Remove-InternalPackageNoise {
    param([string]$PkgStage)
    foreach ($rel in @(
        'engine\packages\README.txt',
        'engine\runtime\README.txt',
        'engine\DO-NOT-EDIT'
    )) {
        $path = Join-Path $PkgStage $rel
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        }
    }
}

try {
Write-Host "PeechaSync setup package build" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot" -ForegroundColor DarkGray

. (Join-Path $ProjectRoot 'tools\ClientRelease-Common.ps1')
. (Join-Path $ProjectRoot 'tools\WP-LicensePlugin-Common.ps1')

$version = Get-ClientAppVersion $ProjectRoot
$setupName = "PeechaSync-Setup-$version-Portable"
$outDir = Join-Path $ProjectRoot 'tools\client-release-deploy'
$buildRoot = Join-Path $outDir '_setup_build'
$stageDir = Join-Path $buildRoot $setupName
$templates = Join-Path $ProjectRoot 'release\installer\templates'
$packageDir = Join-Path $templates '_setup'
$reqClient = Join-Path $ProjectRoot 'release\requirements-client.txt'
$zipPath = Join-Path $outDir "$setupName.zip"
$latestPath = Join-Path $outDir 'latest-portable.zip'

Write-Host "Building $setupName ..." -ForegroundColor Cyan

if (Test-Path -LiteralPath $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stageDir -Force | Out-Null

Copy-TreeFiltered -Source $templates -Destination $stageDir

$toolsStage = Join-Path $stageDir '_tools'
New-Item -ItemType Directory -Path $toolsStage -Force | Out-Null
$checkSrc = Join-Path $ProjectRoot 'tools\Check-PeechaSync.bat'
if (Test-Path -LiteralPath $checkSrc) {
    Copy-Item -LiteralPath $checkSrc -Destination (Join-Path $toolsStage 'Check-PeechaSync.bat') -Force
}
foreach ($helper in @('test-import.ps1', 'test-bootstrap.ps1', 'verify-main-pyc.ps1', 'set-python-env.bat', 'patch-launch-env.cmd', 'repair-launch-env.cmd')) {
    $helperSrc = Join-Path $templates "_setup\engine\app\$helper"
    if (Test-Path -LiteralPath $helperSrc) {
        Copy-Item -LiteralPath $helperSrc -Destination (Join-Path $toolsStage $helper) -Force
    }
}

$iconSrc = Join-Path $ProjectRoot 'release\installer\assets\PeechaSync.ico'
$pkgStage = Join-Path $stageDir '_setup'
if (Test-Path -LiteralPath $iconSrc) {
    Copy-Item -LiteralPath $iconSrc -Destination (Join-Path $pkgStage 'PeechaSync.ico') -Force
    Copy-Item -LiteralPath $iconSrc -Destination (Join-Path $stageDir 'PeechaSync.ico') -Force
}

$appDir = Join-Path $pkgStage 'engine\app'
New-Item -ItemType Directory -Path $appDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'main.py') -Destination $appDir -Force
Copy-Item -LiteralPath $reqClient -Destination (Join-Path $appDir 'requirements.txt') -Force
$runnerBat = Join-Path $templates '_setup\engine\app\Run-PeechaSync.bat'
foreach ($name in @('Run-PeechaSync.bat', 'Launch-PeechaSync.vbs', 'launch-gui.cmd', 'launch-gui.ps1', 'patch-launch-env.cmd', 'repair-launch-env.cmd', 'set-python-env.bat', 'test-import.ps1', 'test-bootstrap.ps1', 'verify-main-pyc.ps1', 'show-startup-error.bat', 'show-user-message.ps1', 'check-internet.bat', 'peecha-version-refresh.ps1', 'Apply-ClientUpdate.ps1', 'peecha-apply-cached-update.ps1', 'Apply-CachedUpdate.bat', 'kill-peecha-processes.ps1')) {
    $src = Join-Path $templates "_setup\engine\app\$name"
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $appDir $name) -Force
    }
}
if (Test-Path -LiteralPath $runnerBat) {
    Copy-Item -LiteralPath $runnerBat -Destination (Join-Path $appDir 'Run-PeechaSync.bat') -Force
}
Copy-TreeFiltered `
    -Source (Join-Path $ProjectRoot 'sync_app') `
    -Destination (Join-Path $appDir 'sync_app') `
    -SkipNames @('license_generator.py', 'license.json.example')

$packagesDir = Join-Path $pkgStage 'engine\packages'
Ensure-InstallWheels -ProjectRoot $ProjectRoot -DestDir $packagesDir

$bundledPyDir = Join-Path $pkgStage 'engine\runtime\python'
$setupBundled = Join-Path $ProjectRoot 'release\setup_bundled_python.ps1'
if ($IsWindows -or $env:OS -eq 'Windows_NT') {
    Write-Host "Building bundled Python runtime ..." -ForegroundColor DarkGray
    & $setupBundled -ProjectRoot $ProjectRoot -DestDir $bundledPyDir -WheelsDir $packagesDir -RequirementsFile $reqClient
} else {
    throw 'Bundled Python must be built on Windows. Run tools\Run_Build_SetupPackage.bat on a Windows PC.'
}

$bundledPy = Join-Path $bundledPyDir 'python.exe'
if (-not (Test-Path -LiteralPath $bundledPy)) {
    throw "bundled python.exe not found: $bundledPy"
}

Write-Host "Compiling to .pyc with bundled Python ..." -ForegroundColor DarkGray
& $bundledPy -m compileall -b -q $appDir
if ($LASTEXITCODE -ne 0) {
    throw "compileall failed (exit $LASTEXITCODE)"
}

$mainPy = Join-Path $appDir 'main.py'
Get-ChildItem -LiteralPath $appDir -Recurse -Filter '*.py' -ErrorAction SilentlyContinue |
    Where-Object { -not $_.PSIsContainer } |
    Remove-Item -Force
Get-ChildItem -LiteralPath $appDir -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

$mainPyc = Join-Path $appDir 'main.pyc'
if (-not (Test-Path -LiteralPath $mainPyc)) {
    throw 'main.pyc not created'
}

$verifyScript = Join-Path $appDir 'verify-main-pyc.ps1'
$bootstrapScript = Join-Path $appDir 'test-bootstrap.ps1'
if ((Test-Path -LiteralPath $verifyScript) -and (Test-Path -LiteralPath $bootstrapScript)) {
    & $verifyScript -PythonExe $bundledPy -MainPyc $mainPyc -InstallDir $appDir -TimeoutSec 20
    if ($LASTEXITCODE -ne 0) {
        throw 'main.pyc verify failed (Python version mismatch or corrupt build?)'
    }
    & $bootstrapScript -PythonExe $bundledPy -InstallDir $appDir -TimeoutSec 25
    if ($LASTEXITCODE -ne 0) {
        throw 'bootstrap verify failed (sync_app import or PYTHONPATH issue in build)'
    }
} else {
    $verifyCode = @"
import marshal
with open(r'$mainPyc', 'rb') as f:
    f.read(16)
    marshal.loads(f.read())
print('pyc ok')
"@
    & $bundledPy -c $verifyCode 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'main.pyc verify failed (Python version mismatch?)'
    }
}
Set-Content -LiteralPath (Join-Path $appDir '.peecha-pyc-only') -Value $version -Encoding ASCII

if (Test-Path -LiteralPath $iconSrc) {
    Copy-Item -LiteralPath $iconSrc -Destination (Join-Path $appDir 'PeechaSync.ico') -Force
    $coreDir = Join-Path $appDir 'sync_app\core'
    if (Test-Path -LiteralPath $coreDir) {
        Copy-Item -LiteralPath $iconSrc -Destination (Join-Path $coreDir 'PeechaSync.ico') -Force
        Copy-Item -LiteralPath $iconSrc -Destination (Join-Path $coreDir 'Peecha_logo.ico') -Force
    }
}

Set-Content -LiteralPath (Join-Path $pkgStage 'VERSION.txt') -Value $version -Encoding ASCII
Set-Content -LiteralPath (Join-Path $stageDir 'VERSION.txt') -Value $version -Encoding ASCII

Remove-InternalPackageNoise -PkgStage $pkgStage
Hide-PackageDir -Path (Join-Path $stageDir '_setup')
Hide-PackageDir -Path (Join-Path $stageDir '_tools')

if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
if (Test-Path -LiteralPath $latestPath) { Remove-Item -LiteralPath $latestPath -Force }

New-PluginFolderZip -sourceDir $stageDir -zipPath $zipPath -folderName $setupName
Copy-Item -LiteralPath $zipPath -Destination $latestPath -Force

Remove-Item -LiteralPath $buildRoot -Recurse -Force

$sizeKb = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1KB, 1)
Write-Host ""
Write-Host "OK: $zipPath ($sizeKb KB)" -ForegroundColor Green
Write-Host "Also: $latestPath" -ForegroundColor Green

} catch {
    Write-Host ""
    Write-Host "SETUP PACKAGE BUILD FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($_.ScriptStackTrace) {
        Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    }
    exit 1
}
