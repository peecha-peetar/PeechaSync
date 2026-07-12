#Requires -Version 5.1

function Get-ClientAppVersion([string]$ProjectRoot) {
    $path = Join-Path $ProjectRoot 'sync_app\core\app_version.py'
    if (-not (Test-Path -LiteralPath $path)) {
        throw "app_version.py not found: $path"
    }
    foreach ($line in Get-Content -LiteralPath $path -Encoding UTF8) {
        if ($line -match '_BUILTIN_VERSION\s*=\s*"(?<ver>[0-9.]+)"') {
            return $Matches['ver'].Trim()
        }
        if ($line -match 'APP_VERSION\s*=\s*"(?<ver>[0-9.]+)"') {
            return $Matches['ver'].Trim()
        }
    }
    throw 'Version not found in app_version.py (_BUILTIN_VERSION or APP_VERSION)'
}

function Ensure-ClientWheels {
    param([string]$ProjectRoot)

    $wheelsSrc = Join-Path $ProjectRoot 'release\installer\wheels'
    $wheelFiles = @(Get-ChildItem -LiteralPath $wheelsSrc -Filter '*.whl' -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer -and $_.Name -notmatch 'cp311-cp311' })

    $needRefresh = $false
    if ($wheelFiles.Count -lt 1) {
        $needRefresh = $true
    } else {
        $pyodbc312 = $wheelFiles | Where-Object { $_.Name -match '^pyodbc-.*cp312' } | Select-Object -First 1
        $crypto = $wheelFiles | Where-Object { $_.Name -match '^cryptography-' } | Select-Object -First 1
        if (-not $pyodbc312 -or -not $crypto) { $needRefresh = $true }
    }
    if ($needRefresh) {
        Write-Host "Downloading offline install wheels (cp312) ..." -ForegroundColor DarkGray
        if (Test-Path -LiteralPath $wheelsSrc) {
            Get-ChildItem -LiteralPath $wheelsSrc -Filter '*.whl' -ErrorAction SilentlyContinue |
                Where-Object { -not $_.PSIsContainer } |
                ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }
        }
        $dlPs1 = Join-Path $ProjectRoot 'release\download_install_wheels.ps1'
        $dlSh = Join-Path $ProjectRoot 'release\download_install_wheels.sh'
        if (Test-Path -LiteralPath $dlPs1) {
            & $dlPs1 -ProjectRoot $ProjectRoot | Out-Null
        } elseif (Test-Path -LiteralPath $dlSh) {
            & bash $dlSh | Out-Null
        } else {
            throw 'Wheel download script not found.'
        }
        $wheelFiles = @(Get-ChildItem -LiteralPath $wheelsSrc -Filter '*.whl' -ErrorAction SilentlyContinue |
            Where-Object { -not $_.PSIsContainer -and $_.Name -notmatch 'cp311-cp311' })
    }
    if ($wheelFiles.Count -lt 1) {
        throw "No wheels in $wheelsSrc"
    }
    $sizeMb = [math]::Round((($wheelFiles | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
    Write-Host "Offline wheels: $($wheelFiles.Count) files ($sizeMb MB)" -ForegroundColor DarkGray
    return $wheelsSrc
}

function Add-OfflineBundleToClientBuild {
    param(
        [string]$ProjectRoot,
        [string]$BuildDir
    )

    if (-not $IsWindows -and $env:OS -ne 'Windows_NT') {
        throw 'Offline OTA bundle (python + wheels) must be built on Windows. Run tools\Run_Build_ClientUpdate.bat'
    }

    $reqClient = Join-Path $ProjectRoot 'release\requirements-client.txt'
    if (-not (Test-Path -LiteralPath $reqClient)) {
        throw "requirements-client.txt not found: $reqClient"
    }

    Write-Host "Step 2/4: offline wheels + python runtime ..." -ForegroundColor DarkGray
    $wheelsSrc = [string](Ensure-ClientWheels -ProjectRoot $ProjectRoot)

    $wheelFiles = @(Get-ChildItem -LiteralPath $wheelsSrc -Filter '*.whl' -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer -and $_.Name -notmatch 'cp311-cp311' })

    $packagesDir = Join-Path $BuildDir '_packages'
    New-Item -ItemType Directory -Path $packagesDir -Force | Out-Null
    foreach ($whl in $wheelFiles) {
        Copy-Item -LiteralPath $whl.FullName -Destination (Join-Path $packagesDir $whl.Name) -Force
    }
    if ($wheelFiles.Count -lt 1) {
        throw "No wheels in $wheelsSrc - delete release\installer\wheels and rebuild"
    }

    Copy-Item -LiteralPath $reqClient -Destination (Join-Path $BuildDir 'requirements.txt') -Force

    $pythonDir = Join-Path $BuildDir 'python'
    $setupBundled = Join-Path $ProjectRoot 'release\setup_bundled_python.ps1'
    & $setupBundled -ProjectRoot $ProjectRoot -DestDir $pythonDir -WheelsDir $wheelsSrc -RequirementsFile $reqClient
}

function Test-ClientReleaseZip {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ZipPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion
    )

    if (-not (Test-Path -LiteralPath $ZipPath)) {
        throw "ZIP not found: $ZipPath"
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $names = @($zip.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
        $required = @(
            'main.py',
            'requirements.txt',
            'VERSION.txt',
            'sync_app/core/app_version.py',
            'Run-PeechaSync.bat',
            'python/python.exe',
            'Force-CleanProgramFiles.ps1',
            'Assert-InstalledVersion.ps1',
            'peecha-version-refresh.ps1',
            'peecha-apply-cached-update.ps1',
            'Apply-ClientUpdate.ps1',
            'Apply-CachedUpdate.bat'
        )
        foreach ($item in $required) {
            $hit = $names | Where-Object { $_ -eq $item -or $_ -like "*/$item" }
            if (-not $hit) {
                throw "ZIP missing required file: $item"
            }
        }
        $hasWheel = $names | Where-Object { $_ -like '_packages/*.whl' -or $_ -like '*/_packages/*.whl' }
        if (-not $hasWheel) {
            throw 'ZIP missing offline wheels in _packages/'
        }
        $verEntry = $zip.Entries | Where-Object { $_.FullName -replace '\\', '/' -match 'sync_app/core/app_version\.py$' } | Select-Object -First 1
        if (-not $verEntry) {
            throw 'app_version.py not found in ZIP'
        }
        $reader = New-Object System.IO.StreamReader($verEntry.Open())
        try {
            $text = $reader.ReadToEnd()
        } finally {
            $reader.Dispose()
        }

        $versionOk = $false
        $verTxtEntry = $zip.Entries | Where-Object { $_.FullName -replace '\\', '/' -match '^VERSION\.txt$' } | Select-Object -First 1
        if ($verTxtEntry) {
            $tr = New-Object System.IO.StreamReader($verTxtEntry.Open())
            try {
                $verFromTxt = ($tr.ReadToEnd() -replace '\s', '').Trim()
            } finally {
                $tr.Dispose()
            }
            if ($verFromTxt -eq $ExpectedVersion) {
                $versionOk = $true
            }
        }
        if (-not $versionOk -and ($text -match "_BUILTIN_VERSION\s*=\s*`"$([regex]::Escape($ExpectedVersion))`"")) {
            $versionOk = $true
        }
        if (-not $versionOk -and ($text -match "APP_VERSION\s*=\s*`"$([regex]::Escape($ExpectedVersion))`"")) {
            $versionOk = $true
        }
        if (-not $versionOk) {
            throw "ZIP version mismatch: expected $ExpectedVersion (check VERSION.txt or _BUILTIN_VERSION)"
        }

        $zipSizeMb = [math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1MB, 1)
        if ($zipSizeMb -lt 40) {
            throw "ZIP too small (${zipSizeMb} MB) - offline python/wheels probably missing"
        }
        Write-Host "ZIP size: ${zipSizeMb} MB" -ForegroundColor DarkGray
    } finally {
        $zip.Dispose()
    }
    Write-Host "ZIP verified: $ZipPath (v$ExpectedVersion)" -ForegroundColor Green
}

function Build-ClientReleaseZip {
    param(
        [string]$ProjectRoot,
        [string]$ToolsRoot,
        [string]$OutDir = ''
    )

    . (Join-Path $ToolsRoot 'WP-LicensePlugin-Common.ps1')

    $version = Get-ClientAppVersion $ProjectRoot
    if (-not $OutDir) {
        $OutDir = Join-Path $ToolsRoot 'client-release-deploy'
    }
    if (-not (Test-Path -LiteralPath $OutDir)) {
        New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    }

    $buildDir = Join-Path $OutDir '_build'
    if (Test-Path -LiteralPath $buildDir) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }

    $copyScript = Join-Path $ProjectRoot 'release\copy_release.ps1'
    if (-not (Test-Path -LiteralPath $copyScript)) {
        throw "copy_release.ps1 not found: $copyScript"
    }

    Write-Host "Build client release v$version ..."
    Write-Host "Step 1/4: copy project files (may take 1-3 min)..." -ForegroundColor DarkGray
    & $copyScript -SourceRoot $ProjectRoot -TargetRoot $buildDir

    Add-OfflineBundleToClientBuild -ProjectRoot $ProjectRoot -BuildDir $buildDir

    $zipName = "PeechaSync-$version.zip"
    $zipPath = Join-Path $OutDir $zipName
    $latestPath = Join-Path $OutDir 'latest.zip'

    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    if (Test-Path -LiteralPath $latestPath) {
        Remove-Item -LiteralPath $latestPath -Force
    }

    Write-Host "Step 3/4: create ZIP (may take a few minutes)..." -ForegroundColor DarkGray
    New-PluginFlatZip $buildDir $zipPath
    Copy-Item -LiteralPath $zipPath -Destination $latestPath -Force
    Write-Host "Step 4/4: verify ZIP ..." -ForegroundColor DarkGray
    Test-ClientReleaseZip -ZipPath $zipPath -ExpectedVersion $version

    Write-Host "Cleanup temp folder..." -ForegroundColor DarkGray
    try {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    } catch {
        Write-Host "Note: could not remove temp build folder: $buildDir" -ForegroundColor DarkYellow
    }

    return [pscustomobject]@{
        Version    = $version
        ZipPath    = $zipPath
        LatestPath = $latestPath
        ZipName    = $zipName
        OutDir     = $OutDir
    }
}

function Get-ClientMirrorRemoteDir([string]$RemotePluginDir, [string]$Configured = '') {
    if ($Configured) {
        return ($Configured -replace '\\', '/').Trim('/')
    }
    $base = ($RemotePluginDir -replace '\\', '/').Trim('/')
    if ($base -match 'plugins/peecha-license-manager$') {
        return ($base -replace 'plugins/peecha-license-manager$', 'uploads/peecha-sync-updates')
    }
    return 'public_html/wp-content/uploads/peecha-sync-updates'
}
