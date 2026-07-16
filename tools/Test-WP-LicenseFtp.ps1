#Requires -Version 5.1
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'wp-license-deploy.local.json')
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WP-LicensePlugin-Common.ps1')
. (Join-Path $PSScriptRoot 'WP-LicensePlugin-Ftp.ps1')

function Read-DeployConfig([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Config not found: $path`nRun Setup_WP_LicenseDeploy.bat first."
    }
    $raw = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    return ($raw | ConvertFrom-Json)
}

Write-LmStep "FTP connection test"

$config = Read-DeployConfig $ConfigPath
$hostName = [string]$config.ftpHost
$port = if ($config.ftpPort) { [int]$config.ftpPort } else { 21 }
$user = [string]$config.ftpUser
$pass = [string]$config.ftpPassword
$useFtps = ($config.useFtps -eq $true)
$usePassive = ($config.usePassive -ne $false)

if (-not $hostName -or -not $user -or -not $pass) {
    throw 'Set ftpHost, ftpUser, ftpPassword in wp-license-deploy.local.json'
}

$curl = Get-CurlExe
Write-Host "curl: $curl"
Write-Host "host: $hostName  user: $user  FTPS: $useFtps"
Write-Host ""

$paths = @(
    [string]$config.remotePluginDir,
    'public_html/wp-content/plugins/peecha-license-manager',
    'wp-content/plugins/peecha-license-manager',
    'domains/peecha.ir/public_html/wp-content/plugins/peecha-license-manager',
    ''
) | Where-Object { $_ -ne $null } | Select-Object -Unique

if ($config.remotePluginDir -match '(?i)domains/[^/]+/(.+)$') {
    $rel = $Matches[1]
    $paths = @($rel) + $paths | Select-Object -Unique
}

$scheme = if ($useFtps) { 'ftps' } else { 'ftp' }
$found = $null

foreach ($path in $paths) {
    $label = if ($path) { $path } else { '(FTP root)' }
    Write-Host "Try list: $label" -ForegroundColor Cyan
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $r = Test-CurlFtpList -CurlExe $curl -Scheme $scheme -HostName $hostName -Port $port `
        -RemoteDir $path -User $user -Password $pass -UsePassive $usePassive -UseFtps $useFtps -DisableEpsv $false
    $ErrorActionPreference = $prevEap
    if ($r.Ok) {
        Write-Host "  OK" -ForegroundColor Green
        if ($r.Output) {
            $preview = ($r.Output -split "`n" | Select-Object -First 8) -join ', '
            Write-Host "  $preview"
        }
        if ($path -and -not $found) { $found = $path }
    } else {
        Write-Host "  fail" -ForegroundColor DarkYellow
        if ($r.Output) { Write-Host "  $($r.Output)" -ForegroundColor DarkGray }
    }
}

if (-not $useFtps) {
    Write-Host ""
    Write-Host "Retry with FTPS..." -ForegroundColor Cyan
    foreach ($path in $paths) {
        if (-not $path) { continue }
        Write-Host "Try FTPS list: $path" -ForegroundColor Cyan
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $r = Test-CurlFtpList -CurlExe $curl -Scheme 'ftps' -HostName $hostName -Port $port `
            -RemoteDir $path -User $user -Password $pass -UsePassive $usePassive -UseFtps $true -DisableEpsv $false
        $ErrorActionPreference = $prevEap
        if ($r.Ok) {
            Write-Host "  OK - set useFtps: true in json" -ForegroundColor Green
            if (-not $found) { $found = $path }
            break
        }
    }
}

Write-Host ""
if ($found) {
    Write-Host "Suggested remotePluginDir:" -ForegroundColor Green
    Write-Host "  `"$found`""
    if ($found -ne [string]$config.remotePluginDir) {
        Write-Host "Update wp-license-deploy.local.json then run deploy again." -ForegroundColor Yellow
    } else {
        Write-Host "Path matches config. Run deploy again." -ForegroundColor Yellow
    }
} else {
    Write-Host "No path worked." -ForegroundColor Red
    Write-Host "Check ftpHost (DirectAdmin server name), user/password, or FTP account for peecha.ir."
    exit 1
}
