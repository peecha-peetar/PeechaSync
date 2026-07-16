#Requires -Version 5.1
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [ValidateSet('install', 'remove')]
    [string]$Action = 'install'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WP-LicensePlugin-Common.ps1')

$pkg = Build-WP-LicensePluginPackage -ProjectRoot $ProjectRoot -ToolsRoot $PSScriptRoot `
    -Action $Action -IncludeWebInstaller -CreateZip

Write-LmStep "Done"
Write-Host "Deploy folder:" -ForegroundColor Green
Write-Host "  $($pkg.DeployDir)"
Write-Host ""
Write-Host "Recommended: wp-admin -> Peecha Licenses -> Update plugin -> upload update.zip" -ForegroundColor Green
Write-Host "Or web-update: upload update.zip + web-update.php, open INSTALL-URL.txt" -ForegroundColor Yellow
Write-Host ""
Write-Host "Opening deploy folder..."
Start-Process explorer.exe $pkg.DeployDir

Set-Clipboard -Value $pkg.WebUpdateUrl
Write-Host "Web update URL copied to clipboard." -ForegroundColor Green
