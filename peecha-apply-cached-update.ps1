#Requires -Version 5.1
param(
    [string]$InstallRoot = '',
    [switch]$Force
)

$ErrorActionPreference = 'SilentlyContinue'

function Get-InstallRoot([string]$fallback) {
    $locFile = Join-Path $env:LOCALAPPDATA 'PeechaSync\install.loc'
    if (Test-Path -LiteralPath $locFile) {
        $fromLoc = (Get-Content -LiteralPath $locFile -Raw -Encoding UTF8).Trim()
        if ($fromLoc -and (Test-Path -LiteralPath $fromLoc)) {
            return $fromLoc.TrimEnd('\', '/')
        }
    }
    if ($fallback) {
        return $fallback.TrimEnd('\', '/')
    }
    return ''
}

function Read-AppVersion([string]$root) {
    $verFile = Join-Path $root 'VERSION.txt'
    if (Test-Path -LiteralPath $verFile) {
        return (Get-Content -LiteralPath $verFile -Raw -Encoding UTF8).Trim()
    }
    $verPy = Join-Path $root 'sync_app\core\app_version.py'
    if (-not (Test-Path -LiteralPath $verPy)) { return '' }
    foreach ($line in Get-Content -LiteralPath $verPy -Encoding UTF8) {
        if ($line -match '_BUILTIN_VERSION\s*=\s*"([^"]+)"') { return $Matches[1].Trim() }
        if ($line -match 'APP_VERSION\s*=\s*"([^"]+)"') { return $Matches[1].Trim() }
    }
    return ''
}

function Version-Tuple([string]$ver) {
    $parts = @()
    foreach ($piece in ($ver -split '\.')) {
        $n = 0
        [void][int]::TryParse($piece, [ref]$n)
        $parts += $n
    }
    if ($parts.Count -eq 0) { return @(0) }
    return $parts
}

function Version-Compare([string]$a, [string]$b) {
    $ta = Version-Tuple $a
    $tb = Version-Tuple $b
    $len = [Math]::Max($ta.Count, $tb.Count)
    for ($i = 0; $i -lt $len; $i++) {
        $va = if ($i -lt $ta.Count) { $ta[$i] } else { 0 }
        $vb = if ($i -lt $tb.Count) { $tb[$i] } else { 0 }
        if ($va -lt $vb) { return -1 }
        if ($va -gt $vb) { return 1 }
    }
    return 0
}

function Read-ZipVersion([string]$zipPath) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        foreach ($entryPath in @('VERSION.txt', 'sync_app/core/app_version.py')) {
            $entry = $zip.Entries |
                Where-Object { $_.FullName -replace '\\', '/' -eq $entryPath } |
                Select-Object -First 1
            if (-not $entry) { continue }
            $stream = $entry.Open()
            $reader = New-Object System.IO.StreamReader($stream)
            try {
                $text = $reader.ReadToEnd()
            } finally {
                $reader.Dispose()
                $stream.Dispose()
            }
            if ($entryPath -eq 'VERSION.txt') {
                $v = $text.Trim()
                if ($v) { return $v }
            }
            if ($text -match '_BUILTIN_VERSION\s*=\s*"([^"]+)"') { return $Matches[1].Trim() }
            if ($text -match 'APP_VERSION\s*=\s*"([^"]+)"') { return $Matches[1].Trim() }
        }
    } finally {
        $zip.Dispose()
    }
    return ''
}

function Write-Log([string]$msg) {
    $logDir = Join-Path $env:LOCALAPPDATA 'PeechaSync'
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    $path = Join-Path $logDir 'update-last.log'
    Add-Content -LiteralPath $path -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] cached-apply $msg" -Encoding UTF8
}

function Test-ApplyBlocked {
    $failFile = Join-Path $env:LOCALAPPDATA 'PeechaSync\update-apply-failed.json'
    if (-not (Test-Path -LiteralPath $failFile)) { return $false }
    try {
        $data = Get-Content -LiteralPath $failFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $atRaw = [string]$data.at
        if (-not $atRaw) { return $false }
        $failedAt = [datetime]::Parse($atRaw, $null, [Globalization.DateTimeStyles]::RoundtripKind)
        $ageHours = ((Get-Date) - $failedAt).TotalHours
        return ($ageHours -lt 24)
    } catch {
        return $false
    }
}

$install = Get-InstallRoot $InstallRoot
if (-not $install) { exit 0 }

if (-not $Force -and (Test-ApplyBlocked)) {
    Write-Log 'skipped (recent apply failure — use Apply-CachedUpdate.bat -Force or Setup ZIP)'
    exit 0
}

$installedVer = Read-AppVersion $install
$cacheDir = Join-Path $env:TEMP 'PeechaSync-updates'
if (-not (Test-Path -LiteralPath $cacheDir)) { exit 0 }

$jobFile = Join-Path $env:LOCALAPPDATA 'PeechaSync\pending-update.json'
$pickZip = ''
$pickVer = ''
if (Test-Path -LiteralPath $jobFile) {
    try {
        $job = Get-Content -LiteralPath $jobFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $candidate = [string]$job.zip
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            $pickZip = $candidate
            $pickVer = Read-ZipVersion $candidate
        }
    } catch {}
}

if (-not $pickZip) {
    foreach ($zip in Get-ChildItem -LiteralPath $cacheDir -Filter 'PeechaSync-*.zip' -File | Sort-Object LastWriteTime -Descending) {
        $ver = Read-ZipVersion $zip.FullName
        if (-not $ver) { continue }
        if (-not $installedVer -or (Version-Compare $ver $installedVer) -gt 0) {
            $pickZip = $zip.FullName
            $pickVer = $ver
            break
        }
    }
}

if (-not $pickZip -or -not $pickVer) { exit 0 }
if ($installedVer -and (Version-Compare $pickVer $installedVer) -le 0) { exit 0 }

Write-Log "start install=$install installed=$installedVer zip=$pickZip target=$pickVer"

$staging = Join-Path $env:LOCALAPPDATA 'PeechaSync\update-bootstrap'
if (Test-Path -LiteralPath $staging) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
New-Item -ItemType Directory -Path $staging -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($pickZip, $staging)

$source = $staging
if (-not (Test-Path -LiteralPath (Join-Path $source 'sync_app'))) {
    $inner = Get-ChildItem -LiteralPath $staging -Directory | Select-Object -First 1
    if ($inner) { $source = $inner.FullName }
}
if (-not (Test-Path -LiteralPath (Join-Path $source 'sync_app'))) {
    Write-Log 'invalid zip structure'
    exit 1
}

$apply = Join-Path $source 'Apply-ClientUpdate.ps1'
if (-not (Test-Path -LiteralPath $apply)) {
    $apply = Join-Path $install 'Apply-ClientUpdate.ps1'
}
if (-not (Test-Path -LiteralPath $apply)) {
    Write-Log 'Apply-ClientUpdate.ps1 missing'
    exit 1
}

$logPath = Join-Path $env:LOCALAPPDATA 'PeechaSync\update-last.log'
& powershell -NoProfile -ExecutionPolicy Bypass -File $apply `
    -InstallRoot $install -SourceRoot $source -LogPath $logPath
if ($LASTEXITCODE -ne 0) {
    Write-Log "apply failed rc=$LASTEXITCODE"
    $stateDir = Join-Path $env:LOCALAPPDATA 'PeechaSync'
    if (-not (Test-Path -LiteralPath $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }
    @{
        at      = (Get-Date).ToString('o')
        reason  = "cached apply failed rc=$LASTEXITCODE"
        install = $install
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $stateDir 'update-apply-failed.json') -Encoding UTF8
    exit $LASTEXITCODE
}

Remove-Item -LiteralPath $jobFile -Force -ErrorAction SilentlyContinue
Write-Log 'done'
