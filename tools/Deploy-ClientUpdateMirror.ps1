#Requires -Version 5.1
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'wp-license-deploy.local.json'),
    [switch]$SkipBuild,
    [switch]$BuildOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ClientRelease-Common.ps1')
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
    if ($SkipBuild) {
        $version = Get-ClientAppVersion $ProjectRoot
        $outDir = Join-Path $PSScriptRoot 'client-release-deploy'
        $zipName = "PeechaSync-$version.zip"
        $zipPath = Join-Path $outDir $zipName
        $latestPath = Join-Path $outDir 'latest.zip'
        if (-not (Test-Path -LiteralPath $zipPath)) {
            throw "ZIP not found (run build first): $zipPath"
        }
        Test-ClientReleaseZip -ZipPath $zipPath -ExpectedVersion $version
        if (-not (Test-Path -LiteralPath $latestPath)) {
            Copy-Item -LiteralPath $zipPath -Destination $latestPath -Force
        }
        $pkg = [pscustomobject]@{
            Version    = $version
            ZipPath    = $zipPath
            LatestPath = $latestPath
            ZipName    = $zipName
            OutDir     = $outDir
        }
        Write-Host "Using existing: $($pkg.ZipName)" -ForegroundColor DarkGray
    } else {
        $pkg = Build-ClientReleaseZip -ProjectRoot $ProjectRoot -ToolsRoot $PSScriptRoot
    }
    Write-Host ""
    Write-Host "Created: $($pkg.ZipName)" -ForegroundColor Green
    Write-Host "Folder: $($pkg.OutDir)" -ForegroundColor Green

    if ($BuildOnly) {
        Write-Host ""
        Write-Host "Build only - upload manually to wp-content/uploads/peecha-sync-updates/" -ForegroundColor Yellow
        exit 0
    }

    $config = Read-DeployConfig $ConfigPath
    $hostName = [string]$config.ftpHost
    $hostAlt = [string]$config.ftpHostAlt
    $port = if ($config.ftpPort) { [int]$config.ftpPort } else { 21 }
    $user = [string]$config.ftpUser
    $pass = [string]$config.ftpPassword
    $remotePluginDir = [string]$config.remotePluginDir
    $remoteMirrorDir = Get-ClientMirrorRemoteDir $remotePluginDir ([string]$config.remoteClientMirrorDir)
    $useFtps = ($config.useFtps -eq $true)
    $usePassive = ($config.usePassive -ne $false)
    $scheme = if ($useFtps) { 'ftps' } else { 'ftp' }

    if (-not $hostName -or -not $user -or -not $pass) {
        throw 'Config must set ftpHost, ftpUser, ftpPassword'
    }

    Write-Host ""
    Write-Host "=== FTP upload client mirror v$($pkg.Version) ===" -ForegroundColor Cyan
    $curl = Get-CurlExe
    $logPath = Join-Path $PSScriptRoot 'client-release-deploy\ftp-mirror-last.log'

    Write-Host "Preflight: test FTP mirror path..."
    $hosts = @($hostName, $hostAlt) | Where-Object { $_ } | Select-Object -Unique
    $probe = @{ Ok = $false }
    foreach ($tryHost in $hosts) {
        Write-Host "  host: $tryHost" -ForegroundColor DarkGray
        $probe = Find-WorkingFtpMirrorDir -CurlExe $curl -Scheme $scheme -HostName $tryHost -Port $port `
            -ConfiguredDir $remoteMirrorDir -User $user -Password $pass -UsePassive $usePassive -UseFtps $useFtps
        if ($probe.Ok) {
            $hostName = $tryHost
            $remoteMirrorDir = $probe.Path
            break
        }
        if ($probe.AuthFailed) {
            # رمز اشتباهه — امتحان‌کردنِ host جایگزین هم فایده نداره (اغلب
            # همون سرورِ فیزیکیه با اسمِ دیگه) و فقط یه Login ناموفقِ دیگه با
            # همون رمز ثبت می‌کنه. فوراً متوقف می‌شیم تا IP بلاک نشه.
            break
        }
    }
    if ($probe.AuthFailed) {
        throw @"
FTP login failed (530/531) - رمز یا یوزرِ FTP در wp-license-deploy.local.json اشتباهه.

برای جلوگیری از بلاک‌شدنِ IP توسطِ هاست، دیگه تلاشِ خودکار نمی‌کنیم. مراحل:
1) DirectAdmin -> FTP Accounts -> $user -> reset password
2) tools\Setup_WP_LicenseDeploy.bat -> رمزِ جدید را Save کنید
3) چند دقیقه صبر کنید (اگه هاست IP رو موقتاً بلاک کرده باشه، خودش باز می‌شه)
4) tools\Test-WP-LicenseFtp.bat تا OK بشه
5) tools\Run_Deploy_ClientUpdate.bat upload-only
"@
    }
    if (-not $probe.Ok) {
        throw @"
FTP mirror path not reachable: $remoteMirrorDir

1) DirectAdmin -> FTP Accounts -> $user -> reset password
2) tools\Setup_WP_LicenseDeploy.bat -> Save
3) tools\Test-WP-LicenseFtp.bat until OK
4) tools\Run_Deploy_ClientUpdate.bat upload-only
"@
    }
    if ($probe.CreatedOnUpload) {
        Write-Host "Mirror folder will be created on upload." -ForegroundColor Yellow
    }
    if ($probe.NeedFtps -and -not $useFtps) {
        $useFtps = $true
        $scheme = 'ftps'
    }
    if ($probe.ContainsKey('Passive')) {
        $usePassive = [bool]$probe.Passive
    }
    $disableEpsv = $false
    if ($probe.ContainsKey('DisableEpsv')) {
        $disableEpsv = [bool]$probe.DisableEpsv
    }

    Write-Host "Target: ${scheme}://${hostName}/${remoteMirrorDir}" -ForegroundColor Cyan
    Write-Host ""

    foreach ($item in @(
            @{ Local = $pkg.ZipPath; Name = $pkg.ZipName },
            @{ Local = $pkg.LatestPath; Name = 'latest.zip' }
        )) {
        $remoteUrl = Get-RemoteFileUrl -Scheme $scheme -HostName $hostName -Port $port `
            -RemoteDir $remoteMirrorDir -RelativePath $item.Name
        Write-Host "Upload $($item.Name) ..."
        Invoke-CurlUpload -CurlExe $curl -LocalPath $item.Local -RemoteUrl $remoteUrl `
            -User $user -Password $pass -UsePassive $usePassive -UseFtps $useFtps `
            -DisableEpsv $disableEpsv -LogPath $logPath
    }

    Write-Host ""
    Write-Host "Client mirror deployed: v$($pkg.Version)" -ForegroundColor Green
    Write-Host "DirectAdmin path:" -ForegroundColor Yellow
    Write-Host "  wp-content/uploads/peecha-sync-updates/$($pkg.ZipName)" -ForegroundColor White

    if ($remotePluginDir) {
        Write-Host ""
        Write-Host "Cleanup: remove stray ZIPs from plugin folder (if any)..." -ForegroundColor DarkGray
        foreach ($name in @($pkg.ZipName, 'latest.zip')) {
            Remove-FtpRemoteFile -CurlExe $curl -Scheme $scheme -HostName $hostName -Port $port `
                -RemoteDir $remotePluginDir -FileName $name -User $user -Password $pass `
                -UsePassive $usePassive -UseFtps $useFtps -DisableEpsv $disableEpsv
        }
    }

    Write-Host ""
    Write-Host "Server reads version from ZIP filename when newer than wp-admin setting." -ForegroundColor Green
    Write-Host "Optional wp-admin: Latest app version = $($pkg.Version), changelog, customer API key in PeechaSync." -ForegroundColor Yellow
} catch {
    Write-Host ""
    Write-Host "CLIENT MIRROR DEPLOY FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Manual: upload tools\client-release-deploy\PeechaSync-*.zip to" -ForegroundColor Yellow
    Write-Host "  wp-content/uploads/peecha-sync-updates/" -ForegroundColor Yellow
    exit 1
}
