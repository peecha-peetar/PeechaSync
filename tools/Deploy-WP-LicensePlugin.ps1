#Requires -Version 5.1
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'wp-license-deploy.local.json'),
    [ValidateSet('update', 'install')]
    [string]$Mode = 'update',
    [switch]$OpenUrl,
    [switch]$AlsoDeployClient
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WP-LicensePlugin-Common.ps1')
. (Join-Path $PSScriptRoot 'WP-LicensePlugin-Ftp.ps1')

function Read-DeployConfig([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        $example = Join-Path $PSScriptRoot 'wp-license-deploy.local.json.example'
        throw @"
Config not found: $path

Run once: tools\Setup_WP_LicenseDeploy.bat
Or copy: `"$example`" -> `"$path`" and set ftpUser / ftpPassword
"@
    }
    $raw = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    return ($raw | ConvertFrom-Json)
}

try {
    $pkg = $null
    $config = Read-DeployConfig $ConfigPath
    $hostName = [string]$config.ftpHost
    $hostAlt = [string]$config.ftpHostAlt
    $port = if ($config.ftpPort) { [int]$config.ftpPort } else { 21 }
    $user = [string]$config.ftpUser
    $pass = [string]$config.ftpPassword
    $remoteDir = [string]$config.remotePluginDir
    $siteUrl = if ($config.siteUrl) { [string]$config.siteUrl.TrimEnd('/') } else { 'https://peecha.ir' }
    $useFtps = ($config.useFtps -eq $true)
    $usePassive = ($config.usePassive -ne $false)
    $scheme = if ($useFtps) { 'ftps' } else { 'ftp' }

    if (-not $hostName -or -not $user -or -not $pass -or -not $remoteDir) {
        throw 'Config must set ftpHost, ftpUser, ftpPassword, remotePluginDir'
    }
    if ($user -eq 'YOUR_FTP_USER' -or $pass -eq 'YOUR_FTP_PASSWORD') {
        throw 'Set real ftpUser and ftpPassword in wp-license-deploy.local.json'
    }

    $includeWeb = ($Mode -eq 'install')
    $pkg = Build-WP-LicensePluginPackage -ProjectRoot $ProjectRoot -ToolsRoot $PSScriptRoot `
        -Action $Mode -IncludeWebInstaller:$includeWeb -CreateZip

    Write-LmStep "FTP upload ($Mode) via curl"
    $curl = Get-CurlExe
    $logPath = Join-Path $PSScriptRoot 'wp-license-deploy\ftp-last.log'

    Write-Host "Preflight: test FTP path..."
    $hosts = @($hostName, $hostAlt) | Where-Object { $_ } | Select-Object -Unique
    $probe = @{ Ok = $false }
    foreach ($tryHost in $hosts) {
        Write-Host "  host: $tryHost" -ForegroundColor DarkGray
        $probe = Find-WorkingFtpRemoteDir -CurlExe $curl -Scheme $scheme -HostName $tryHost -Port $port `
            -ConfiguredDir $remoteDir -User $user -Password $pass -UsePassive $usePassive -UseFtps $useFtps
        if ($probe.Ok) {
            $hostName = $tryHost
            break
        }
    }
    if (-not $probe.Ok) {
        throw @"
FTP login or path failed. Check ftpUser/ftpPassword and ftpHost in wp-license-deploy.local.json.
Try ftpHost: server38e.irwebspace.com or set useFtps: true
Or upload update.zip via wp-admin / File Manager (see tools\wp-license-deploy\INSTALL-URL.txt)
"@
    }
    if ($probe.NeedFtps -and -not $useFtps) {
        $useFtps = $true
        $scheme = 'ftps'
        Write-Host "Preflight: FTPS required - enabled for this run." -ForegroundColor Yellow
    }
    if ($probe.ContainsKey('Passive')) {
        $usePassive = [bool]$probe.Passive
    }
    $disableEpsv = $false
    if ($probe.ContainsKey('DisableEpsv')) {
        $disableEpsv = [bool]$probe.DisableEpsv
    }
    if ($probe.Path -ne $remoteDir) {
        Write-Host "Preflight: using path: $($probe.Path)" -ForegroundColor Yellow
        Write-Host "Update remotePluginDir in json to: `"$($probe.Path)`"" -ForegroundColor Yellow
        $remoteDir = $probe.Path
    } else {
        Write-Host "Preflight: OK ($remoteDir)" -ForegroundColor Green
    }

    Write-Host "Target: ${scheme}://${hostName}/${remoteDir}"
    Write-Host "Version: $($pkg.Version)"
    if ($pkg.Version -match '^\d' -and $pkg.Version -lt '1.0.21') {
        throw @"
Local plugin is $($pkg.Version) — upload blocked (need 1.0.31+ on GitHub main).

1) Run from project root: Force-Git-Sync.bat
   or: tools\Run_Sync_Plugin_From_GitHub.bat  (no git)
2) findstr Version wordpress-plugin\peecha-license-manager\peecha-license-manager.php
   must show 1.0.31
3) Run deploy again

افزونه محلی $($pkg.Version) است — آپلود متوقف شد.
اول Force-Git-Sync.bat یا Run_Sync_Plugin_From_GitHub.bat را بزنید.
"@
    }
    Write-Host "Passive: $usePassive  FTPS: $useFtps  disable-epsv: $disableEpsv"
    Write-Host ""

    $exclude = @()
    if ($Mode -eq 'update') {
        $exclude = @('web-install.php')
    }

    Upload-PluginFolderCurl -LocalRoot $pkg.PluginDst -Scheme $scheme -HostName $hostName -Port $port `
        -RemoteDir $remoteDir -User $user -Password $pass -UsePassive $usePassive -UseFtps $useFtps `
        -DisableEpsv $disableEpsv -ExcludeNames $exclude -LogPath $logPath

    Write-LmStep "Done"
    if ($Mode -eq 'update') {
        Write-Host "Plugin updated on server." -ForegroundColor Green
        Write-Host "No wp-admin step needed - refresh the admin page to see v$($pkg.Version)." -ForegroundColor Green
        if ($AlsoDeployClient) {
            Write-Host ""
            & (Join-Path $PSScriptRoot 'Deploy-ClientUpdateMirror.ps1') -ProjectRoot $ProjectRoot -ConfigPath $ConfigPath
        }
    } else {
        $url = "$siteUrl/wp-content/plugins/peecha-license-manager/web-install.php?token=$($pkg.Token)" + '&action=install'
        Write-Host "Files uploaded. Open this URL once:" -ForegroundColor Yellow
        Write-Host "  $url" -ForegroundColor White
        Write-Host "Then delete web-install.php on the server." -ForegroundColor Yellow
        Set-Clipboard -Value $url
        Write-Host "URL copied to clipboard." -ForegroundColor Green
        if ($OpenUrl -or $config.openBrowserAfterDeploy) {
            Start-Process $url
        }
    }
} catch {
    Write-Host ""
    Write-Host "DEPLOY FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    if ($pkg -and $pkg.WebUpdateUrl) {
        Write-Host "Try web update (no wp-admin delete needed):" -ForegroundColor Yellow
        Write-Host "  1) File Manager -> wp-content/plugins/peecha-license-manager/" -ForegroundColor Yellow
        Write-Host "  2) Upload update.zip + web-update.php from tools\wp-license-deploy\peecha-license-manager\" -ForegroundColor Yellow
        Write-Host "  3) Open: $($pkg.WebUpdateUrl)" -ForegroundColor White
    }
    Write-Host ""
    Write-Host "Run: tools\Run_Make_UpdateZip.bat  (build update.zip without FTP)" -ForegroundColor Yellow
    Write-Host "Run: tools\Test_WP_LicenseFtp.bat  (finds correct remotePluginDir)" -ForegroundColor Yellow
    Write-Host "Or upload tools\wp-license-deploy\peecha-license-manager-wp.zip in wp-admin." -ForegroundColor Yellow
    exit 1
}
