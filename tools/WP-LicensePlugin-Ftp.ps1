#Requires -Version 5.1

function Get-CurlExe {
    $sys = Join-Path $env:WINDIR 'System32\curl.exe'
    if (Test-Path -LiteralPath $sys) { return $sys }
    $cmd = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw 'curl.exe not found (need Windows 10+ System32\curl.exe).'
}

function Get-RemoteFileUrl {
    param(
        [string]$Scheme,
        [string]$HostName,
        [int]$Port,
        [string]$RemoteDir,
        [string]$RelativePath = ''
    )
    $base = ($RemoteDir -replace '\\', '/').Trim('/')
    $rel = ($RelativePath -replace '\\', '/').Trim('/')
    $path = if ($rel) { "$base/$rel" } else { $base }
    if ($Port -eq 21 -or $Port -eq 990) {
        return "${Scheme}://${HostName}/${path}"
    }
    return "${Scheme}://${HostName}:${Port}/${path}"
}

function Build-CurlFtpArgs {
    param(
        [string]$User,
        [string]$Password,
        [bool]$UsePassive = $true,
        [bool]$UseFtps = $false,
        [bool]$DisableEpsv = $false,
        [int]$MaxTimeSec = 0,
        [int]$ConnectTimeoutSec = 20,
        [string[]]$Extra = @()
    )
    $curlArgs = @('--silent', '--show-error', '--fail', '--connect-timeout', "$ConnectTimeoutSec") + $Extra
    if ($MaxTimeSec -gt 0) {
        $curlArgs += @('--max-time', "$MaxTimeSec")
    }
    $curlArgs += @('--user', "${User}:${Password}")
    if ($UsePassive) { $curlArgs += '--ftp-pasv' }
    if ($DisableEpsv) { $curlArgs += '--disable-epsv' }
    if ($UseFtps) { $curlArgs += @('--ftp-ssl', '--ssl-reqd') }
    return $curlArgs
}

function Invoke-CurlFtp {
    param(
        [string]$CurlExe,
        [string[]]$CurlArgs,
        [switch]$AllowFail
    )
    $prevEap = $ErrorActionPreference
    if ($AllowFail) {
        $ErrorActionPreference = 'Continue'
    }
    try {
        $output = & $CurlExe @CurlArgs 2>&1 | ForEach-Object { "$_" }
        if (-not $AllowFail -and $LASTEXITCODE -ne 0) {
            $text = ($output | Where-Object { $_ }) -join "`n"
            if (-not $text) { $text = "exit code $LASTEXITCODE" }
            throw $text
        }
        return $output
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Invoke-CurlUpload {
    param(
        [string]$CurlExe,
        [string]$LocalPath,
        [string]$RemoteUrl,
        [string]$User,
        [string]$Password,
        [bool]$UsePassive = $true,
        [bool]$UseFtps = $false,
        [bool]$DisableEpsv = $false,
        [string]$LogPath = ''
    )

    $baseArgs = Build-CurlFtpArgs -User $User -Password $Password -UsePassive $UsePassive `
        -UseFtps $UseFtps -DisableEpsv $DisableEpsv -MaxTimeSec 7200 `
        -Extra @('--ftp-create-dirs', '-T', $LocalPath, $RemoteUrl)

    $first = $null
    $second = $null

    try {
        Invoke-CurlFtp -CurlExe $CurlExe -CurlArgs $baseArgs | Out-Null
        return
    } catch {
        $first = $_.Exception.Message
    }

    if (-not $DisableEpsv) {
        try {
            Write-Host "  retry with disable-epsv..." -ForegroundColor DarkYellow
            $retryArgs = Build-CurlFtpArgs -User $User -Password $Password -UsePassive $UsePassive `
                -UseFtps $UseFtps -DisableEpsv $true -MaxTimeSec 7200 `
                -Extra @('--ftp-create-dirs', '-T', $LocalPath, $RemoteUrl)
            Invoke-CurlFtp -CurlExe $CurlExe -CurlArgs $retryArgs | Out-Null
            return
        } catch {
            $second = $_.Exception.Message
        }
    }

    if (-not $UseFtps) {
        try {
            Write-Host "  retry with FTPS..." -ForegroundColor DarkYellow
            $ftpsUrl = $RemoteUrl -replace '^ftp://', 'ftps://'
            $ftpsArgs = Build-CurlFtpArgs -User $User -Password $Password -UsePassive $UsePassive `
                -UseFtps $true -DisableEpsv $true -MaxTimeSec 7200 `
                -Extra @('--ftp-create-dirs', '-T', $LocalPath, $ftpsUrl)
            Invoke-CurlFtp -CurlExe $CurlExe -CurlArgs $ftpsArgs | Out-Null
            return
        } catch {
            $second = if ($second) { "$second`n$($_.Exception.Message)" } else { $_.Exception.Message }
        }
    }

    Write-Host "  curl verbose:" -ForegroundColor DarkYellow
    $verboseArgs = Build-CurlFtpArgs -User $User -Password $Password -UsePassive $UsePassive `
        -UseFtps $UseFtps -DisableEpsv $true -Extra @('-v', '--ftp-create-dirs', '-T', $LocalPath, $RemoteUrl)
    $verboseOut = @(Invoke-CurlFtp -CurlExe $CurlExe -CurlArgs $verboseArgs -AllowFail)
    if ($LogPath) {
        ($verboseOut | Where-Object { $_ }) | Set-Content -LiteralPath $LogPath -Encoding UTF8
        Write-Host "  log: $LogPath" -ForegroundColor DarkGray
    }
    $interesting = $verboseOut | Where-Object {
        $_ -match '^\* |^< |^> |curl: |530 |531 |550 |421 |425 |Login|denied|refused|timeout|SSL'
    } | ForEach-Object {
        if ($_ -match '^> PASS ') { '> PASS ****' } else { $_ }
    }
    if (-not $interesting) {
        $interesting = $verboseOut | Select-Object -Last 25
    }
    $tail = ($interesting | Select-Object -Last 25) -join "`n"
    if ($tail) { Write-Host $tail -ForegroundColor DarkGray }

    $msg = $first
    if ($second) { $msg = "$first`n$second" }
    if ($tail) { $msg = "$msg`n$tail" }
    throw "upload failed: $msg"
}

function Test-CurlFtpList {
    param(
        [string]$CurlExe,
        [string]$Scheme,
        [string]$HostName,
        [int]$Port,
        [string]$RemoteDir,
        [string]$User,
        [string]$Password,
        [bool]$UsePassive,
        [bool]$UseFtps,
        [bool]$DisableEpsv
    )
    $url = Get-RemoteFileUrl -Scheme $Scheme -HostName $HostName -Port $Port -RemoteDir $RemoteDir
    if (-not $url.EndsWith('/')) { $url += '/' }
    $listArgs = Build-CurlFtpArgs -User $User -Password $Password -UsePassive $UsePassive `
        -UseFtps $UseFtps -DisableEpsv $DisableEpsv -MaxTimeSec 45 -Extra @('--list-only', $url)
    $out = Invoke-CurlFtp -CurlExe $CurlExe -CurlArgs $listArgs -AllowFail
    return @{
        Ok     = ($LASTEXITCODE -eq 0)
        Output = ($out | Where-Object { $_ }) -join "`n"
        Url    = $url
    }
}

function Get-FtpPathCandidates([string]$Configured) {
    $paths = New-Object System.Collections.Generic.List[string]
    if ($Configured) {
        [void]$paths.Add(($Configured -replace '\\', '/').Trim('/'))
    }
    if ($Configured -match '(?i)domains/[^/]+/(.+)$') {
        $rel = $Matches[1].Trim('/')
        if ($rel -and $paths -notcontains $rel) {
            [void]$paths.Add($rel)
        }
    }
    foreach ($p in @(
        'public_html/wp-content/uploads/peecha-sync-updates',
        'public_html/wp-content/plugins/peecha-license-manager',
        'wp-content/uploads/peecha-sync-updates',
        'wp-content/plugins/peecha-license-manager',
        'domains/peecha.ir/public_html/wp-content/plugins/peecha-license-manager'
    )) {
        if ($paths -notcontains $p) {
            [void]$paths.Add($p)
        }
    }
    return @($paths)
}

function Get-MirrorFtpPathCandidates([string]$Configured) {
    $paths = New-Object System.Collections.Generic.List[string]
    if ($Configured) {
        [void]$paths.Add(($Configured -replace '\\', '/').Trim('/'))
    }
    if ($Configured -match '(?i)domains/[^/]+/(.+)$') {
        $rel = $Matches[1].Trim('/')
        if ($rel -and $paths -notcontains $rel) {
            [void]$paths.Add($rel)
        }
    }
    foreach ($p in @(
        'public_html/wp-content/uploads/peecha-sync-updates',
        'wp-content/uploads/peecha-sync-updates'
    )) {
        if ($paths -notcontains $p) {
            [void]$paths.Add($p)
        }
    }
    return @($paths)
}

function Find-WorkingFtpMirrorDir {
    param(
        [string]$CurlExe,
        [string]$Scheme,
        [string]$HostName,
        [int]$Port,
        [string]$ConfiguredDir,
        [string]$User,
        [string]$Password,
        [bool]$UsePassive,
        [bool]$UseFtps
    )
    $modes = @(
        @{ Passive = $true;  DisableEpsv = $false },
        @{ Passive = $true;  DisableEpsv = $true },
        @{ Passive = $false; DisableEpsv = $false },
        @{ Passive = $false; DisableEpsv = $true }
    )
    foreach ($path in (Get-MirrorFtpPathCandidates $ConfiguredDir)) {
        foreach ($mode in $modes) {
            $r = Test-CurlFtpList -CurlExe $CurlExe -Scheme $Scheme -HostName $HostName -Port $Port `
                -RemoteDir $path -User $User -Password $Password -UsePassive $mode.Passive `
                -UseFtps $UseFtps -DisableEpsv $mode.DisableEpsv
            if ($r.Ok) {
                return @{
                    Ok = $true
                    Path = $path
                    ListUrl = $r.Url
                    Passive = $mode.Passive
                    DisableEpsv = $mode.DisableEpsv
                }
            }
        }
        if (-not $UseFtps) {
            foreach ($mode in $modes) {
                $r2 = Test-CurlFtpList -CurlExe $CurlExe -Scheme 'ftps' -HostName $HostName -Port $Port `
                    -RemoteDir $path -User $User -Password $Password -UsePassive $mode.Passive `
                    -UseFtps $true -DisableEpsv $mode.DisableEpsv
                if ($r2.Ok) {
                    return @{
                        Ok = $true
                        Path = $path
                        ListUrl = $r2.Url
                        NeedFtps = $true
                        Passive = $mode.Passive
                        DisableEpsv = $mode.DisableEpsv
                    }
                }
            }
        }
    }

    $fallback = (Get-MirrorFtpPathCandidates $ConfiguredDir) | Select-Object -First 1
    if (-not $fallback) {
        return @{ Ok = $false }
    }
    return @{
        Ok = $true
        Path = $fallback
        Passive = $true
        DisableEpsv = $true
        CreatedOnUpload = $true
    }
}

function Find-WorkingFtpRemoteDir {
    param(
        [string]$CurlExe,
        [string]$Scheme,
        [string]$HostName,
        [int]$Port,
        [string]$ConfiguredDir,
        [string]$User,
        [string]$Password,
        [bool]$UsePassive,
        [bool]$UseFtps
    )
    $modes = @(
        @{ Passive = $true;  DisableEpsv = $false },
        @{ Passive = $true;  DisableEpsv = $true },
        @{ Passive = $false; DisableEpsv = $false },
        @{ Passive = $false; DisableEpsv = $true }
    )
    foreach ($path in (Get-FtpPathCandidates $ConfiguredDir)) {
        foreach ($mode in $modes) {
            $r = Test-CurlFtpList -CurlExe $CurlExe -Scheme $Scheme -HostName $HostName -Port $Port `
                -RemoteDir $path -User $User -Password $Password -UsePassive $mode.Passive `
                -UseFtps $UseFtps -DisableEpsv $mode.DisableEpsv
            if ($r.Ok) {
                return @{
                    Ok = $true
                    Path = $path
                    ListUrl = $r.Url
                    Passive = $mode.Passive
                    DisableEpsv = $mode.DisableEpsv
                }
            }
        }
        if (-not $UseFtps) {
            foreach ($mode in $modes) {
                $r2 = Test-CurlFtpList -CurlExe $CurlExe -Scheme 'ftps' -HostName $HostName -Port $Port `
                    -RemoteDir $path -User $User -Password $Password -UsePassive $mode.Passive `
                    -UseFtps $true -DisableEpsv $mode.DisableEpsv
                if ($r2.Ok) {
                    return @{
                        Ok = $true
                        Path = $path
                        ListUrl = $r2.Url
                        NeedFtps = $true
                        Passive = $mode.Passive
                        DisableEpsv = $mode.DisableEpsv
                    }
                }
            }
        }
    }
    return @{ Ok = $false }
}

function Remove-FtpRemoteFile {
    param(
        [string]$CurlExe,
        [string]$Scheme,
        [string]$HostName,
        [int]$Port,
        [string]$RemoteDir,
        [string]$FileName,
        [string]$User,
        [string]$Password,
        [bool]$UsePassive,
        [bool]$UseFtps,
        [bool]$DisableEpsv = $false
    )
    $dirUrl = Get-RemoteFileUrl -Scheme $Scheme -HostName $HostName -Port $Port -RemoteDir $RemoteDir
    if (-not $dirUrl.EndsWith('/')) {
        $dirUrl += '/'
    }
    $delArgs = Build-CurlFtpArgs -User $User -Password $Password -UsePassive $UsePassive `
        -UseFtps $UseFtps -DisableEpsv $DisableEpsv -Extra @('-Q', "DELE $FileName", $dirUrl)
    Invoke-CurlFtp -CurlExe $CurlExe -CurlArgs $delArgs -AllowFail | Out-Null
}

function Upload-PluginFolderCurl {
    param(
        [string]$LocalRoot,
        [string]$Scheme,
        [string]$HostName,
        [int]$Port,
        [string]$RemoteDir,
        [string]$User,
        [string]$Password,
        [bool]$UsePassive,
        [bool]$UseFtps,
        [bool]$DisableEpsv = $false,
        [string[]]$ExcludeNames = @(),
        [string]$LogPath = ''
    )

    $curl = Get-CurlExe
    $files = Get-ChildItem -LiteralPath $LocalRoot -Recurse -File
    $total = $files.Count
    $n = 0

    foreach ($file in $files) {
        $rel = $file.FullName.Substring($LocalRoot.Length).TrimStart('\')
        $name = Split-Path -Leaf $rel
        if ($ExcludeNames -contains $name) { continue }

        $remoteUrl = Get-RemoteFileUrl -Scheme $Scheme -HostName $HostName -Port $Port `
            -RemoteDir $RemoteDir -RelativePath ($rel -replace '\\', '/')

        $n++
        Write-Host "[$n/$total] $rel"
        Invoke-CurlUpload -CurlExe $curl -LocalPath $file.FullName -RemoteUrl $remoteUrl `
            -User $User -Password $Password -UsePassive $UsePassive -UseFtps $UseFtps `
            -DisableEpsv $DisableEpsv -LogPath $LogPath
    }
}
