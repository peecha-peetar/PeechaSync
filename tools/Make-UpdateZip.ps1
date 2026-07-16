#Requires -Version 5.1
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WP-LicensePlugin-Common.ps1')

function Invoke-TarZip {
    param(
        [string]$ZipPath,
        [string]$WorkDir,
        [string]$Entry = '.'
    )
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (-not (Test-Path -LiteralPath $tar)) {
        throw 'tar.exe not found (Windows 10+ required).'
    }
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Write-Host "tar -a -cf $ZipPath -C $WorkDir $Entry"
    & $tar -a -cf $ZipPath -C $WorkDir $Entry
    if ($LASTEXITCODE -ne 0) {
        throw "tar failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $ZipPath)) {
        throw 'tar finished but zip file missing'
    }
}

try {
    Write-LmStep 'Build plugin folder'
    $pkg = Build-WP-LicensePluginPackage -ProjectRoot $ProjectRoot -ToolsRoot $PSScriptRoot `
        -Action 'update' -CreateZip:$false

    $pluginDst = (Resolve-Path -LiteralPath $pkg.PluginDst).Path
    $updateZip = Join-Path $pkg.DeployDir 'update.zip'
    $wpZip = Join-Path $pkg.DeployDir 'peecha-license-manager.zip'

    Write-LmStep 'Create update.zip (tar)'
    Invoke-TarZip -ZipPath $updateZip -WorkDir $pluginDst -Entry '.'

    Write-LmStep 'Create peecha-license-manager.zip (tar)'
    $parent = Split-Path -Parent $pluginDst
    $leaf = Split-Path -Leaf $pluginDst
    Invoke-TarZip -ZipPath $wpZip -WorkDir $parent -Entry $leaf
    Copy-Item -LiteralPath $wpZip -Destination (Join-Path $pkg.DeployDir 'peecha-license-manager-wp.zip') -Force

    Write-Host ''
    Write-Host 'OK' -ForegroundColor Green
    Write-Host "update.zip -> $updateZip"
    Write-Host "web-update.php -> $(Join-Path $pluginDst 'web-update.php')"
    Write-Host ''
    Write-Host 'Manual upload:' -ForegroundColor Yellow
    Write-Host '  File Manager -> wp-content/plugins/peecha-license-manager/'
    Write-Host '  Upload update.zip + web-update.php'
    Write-Host "  Open: $($pkg.WebUpdateUrl)"
} catch {
    Write-Host ''
    Write-Host "MAKE ZIP FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
