#Requires -Version 5.1

function Write-LmStep([string]$text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Write-InstallerPhp([string]$templatePath, [string]$destPath, [string]$token) {
    $php = Get-Content -LiteralPath $templatePath -Raw -Encoding UTF8
    $php = $php.Replace('__INSTALL_TOKEN__', $token)
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($destPath, $php, $utf8NoBom)
}

function Get-PluginVersion([string]$pluginMain) {
    if (-not (Test-Path -LiteralPath $pluginMain)) { return '?' }
    foreach ($line in Get-Content -LiteralPath $pluginMain -Encoding UTF8) {
        if ($line -match '^\s*\*\s*Version:\s*(.+)$') {
            return $Matches[1].Trim()
        }
    }
    return '?'
}

function New-PluginFlatZip([string]$sourceDir, [string]$zipPath) {
    $sourceDir = (Resolve-Path -LiteralPath $sourceDir).Path.TrimEnd('\')
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path -LiteralPath $tar) {
        & $tar -a -cf $zipPath -C $sourceDir .
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $zipPath)) {
            return
        }
    }
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            Get-ChildItem -LiteralPath $sourceDir -Recurse -File | ForEach-Object {
                $rel = $_.FullName.Substring($sourceDir.Length).TrimStart('\').Replace('\', '/')
                [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $rel)
            }
        } finally {
            $zip.Dispose()
        }
    } catch {
        throw "zip failed: $($_.Exception.Message)"
    }
}

function New-PluginFolderZip([string]$sourceDir, [string]$zipPath, [string]$folderName) {
    $sourceDir = (Resolve-Path -LiteralPath $sourceDir).Path.TrimEnd('\')
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    $parent = Split-Path -Parent $sourceDir
    $leaf = Split-Path -Leaf $sourceDir
    $targetName = ($folderName -replace '[\\/]', '').Trim()
    if (-not $targetName) { $targetName = $leaf }
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path -LiteralPath $tar) {
        if ($targetName -eq $leaf) {
            & $tar -a -cf $zipPath -C $parent $leaf
        } else {
            $stage = Join-Path $env:TEMP ("peecha-zip-" + [guid]::NewGuid().ToString('N'))
            $stageRoot = Join-Path $stage $targetName
            New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
            Copy-Item -Path (Join-Path $sourceDir '*') -Destination $stageRoot -Recurse -Force
            try {
                & $tar -a -cf $zipPath -C $stage $targetName
            } finally {
                Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $zipPath)) {
            return
        }
    }
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
        $prefix = $targetName
        try {
            Get-ChildItem -LiteralPath $sourceDir -Recurse -File | ForEach-Object {
                $rel = $_.FullName.Substring($sourceDir.Length).TrimStart('\').Replace('\', '/')
                $entry = "$prefix/$rel"
                [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $entry)
            }
        } finally {
            $zip.Dispose()
        }
    } catch {
        throw "zip failed: $($_.Exception.Message)"
    }
}

function Clear-DeployPath([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        return $true
    }
    try {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Clear-DeployPathContents([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        return
    }
    foreach ($item in Get-ChildItem -LiteralPath $path -Force) {
        try {
            if ($item.PSIsContainer) {
                Remove-Item -LiteralPath $item.FullName -Recurse -Force -ErrorAction Stop
            } else {
                Remove-Item -LiteralPath $item.FullName -Force -ErrorAction Stop
            }
        } catch {
            Write-Host "Locked, skip: $($item.Name)" -ForegroundColor DarkYellow
        }
    }
}

function Sync-PluginFolder([string]$sourceDir, [string]$destDir) {
    if (-not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    $robocopy = Join-Path $env:SystemRoot 'System32\robocopy.exe'
    if (Test-Path -LiteralPath $robocopy) {
        & $robocopy $sourceDir $destDir /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
        if ($LASTEXITCODE -gt 7) {
            throw "robocopy failed ($LASTEXITCODE)"
        }
        return
    }
    Copy-Item -Path (Join-Path $sourceDir '*') -Destination $destDir -Recurse -Force
}

function Prepare-DeployFolder([string]$deployDir, [string]$pluginDst) {
    if (Test-Path -LiteralPath $deployDir) {
        if (-not (Clear-DeployPath $deployDir)) {
            Write-Host "Deploy folder open in Explorer - refreshing in place." -ForegroundColor Yellow
            Write-Host "Close File Explorer on wp-license-deploy if copy fails." -ForegroundColor Yellow
            Clear-DeployPathContents $deployDir
        }
    }
    if (-not (Test-Path -LiteralPath $deployDir)) {
        New-Item -ItemType Directory -Path $deployDir -Force | Out-Null
    }
    if (Test-Path -LiteralPath $pluginDst) {
        if (-not (Clear-DeployPath $pluginDst)) {
            Clear-DeployPathContents $pluginDst
        }
    }
    New-Item -ItemType Directory -Path $pluginDst -Force | Out-Null
}

function Build-WP-LicensePluginPackage {
    param(
        [string]$ProjectRoot,
        [string]$ToolsRoot,
        [string]$Action = 'install',
        [switch]$IncludeWebInstaller,
        [switch]$CreateZip
    )

    $pluginSrc = Join-Path $ProjectRoot 'wordpress-plugin\peecha-license-manager'
    $rootTemplate = Join-Path $ToolsRoot 'wp-license-install.template.php'
    $webTemplate = Join-Path $ToolsRoot 'wp-web-install.template.php'
    $webUpdateTemplate = Join-Path $ToolsRoot 'wp-web-update.template.php'
    $deployDir = Join-Path $ToolsRoot 'wp-license-deploy'
    $pluginDst = Join-Path $deployDir 'peecha-license-manager'
    $installPhp = Join-Path $deployDir 'peecha-lm-install.php'
    $webInstallPhp = Join-Path $pluginDst 'web-install.php'
    $webUpdatePhp = Join-Path $pluginDst 'web-update.php'
    $wpZipPath = Join-Path $deployDir 'peecha-license-manager.zip'
    $wpZipLegacy = Join-Path $deployDir 'peecha-license-manager-wp.zip'
    $updateZipPath = Join-Path $deployDir 'update.zip'
    $urlFile = Join-Path $deployDir 'INSTALL-URL.txt'

    if (-not (Test-Path $pluginSrc)) {
        throw "Plugin source not found: $pluginSrc"
    }
    if ($IncludeWebInstaller -and -not (Test-Path $webTemplate)) {
        throw "Web installer template not found: $webTemplate"
    }
    if (-not (Test-Path $rootTemplate)) {
        throw "Installer template not found: $rootTemplate"
    }
    if (-not (Test-Path $webUpdateTemplate)) {
        throw "Web update template not found: $webUpdateTemplate"
    }

    Write-LmStep "Prepare deploy folder"
    if (Test-Path -LiteralPath $wpZipPath) {
        try { Remove-Item -LiteralPath $wpZipPath -Force } catch {}
    }
    if (Test-Path -LiteralPath $wpZipLegacy) {
        try { Remove-Item -LiteralPath $wpZipLegacy -Force } catch {}
    }
    if (Test-Path -LiteralPath $updateZipPath) {
        try { Remove-Item -LiteralPath $updateZipPath -Force } catch {}
    }
    Prepare-DeployFolder $deployDir $pluginDst

    Write-Host "Copy plugin files..."
    Sync-PluginFolder $pluginSrc $pluginDst

    $token = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    Write-InstallerPhp $rootTemplate $installPhp $token
    Write-InstallerPhp $webUpdateTemplate $webUpdatePhp $token

    $webInstallUrl = $null
    $rootInstallUrl = $null
    $webUpdateUrl = $null
    $baseUrl = 'https://peecha.ir'
    if ($IncludeWebInstaller) {
        Write-InstallerPhp $webTemplate $webInstallPhp $token
        $webInstallUrl = "$baseUrl/wp-content/plugins/peecha-license-manager/web-install.php?token=$token" + '&action=' + $Action
        $rootInstallUrl = "$baseUrl/peecha-lm-install.php?token=$token" + '&action=' + $Action
    }
    $webUpdateUrl = "$baseUrl/wp-content/plugins/peecha-license-manager/web-update.php?token=$token"

    $urlText = @(
        "=== RECOMMENDED: in-plugin update (no wp-admin delete) ==="
        "1) wp-admin -> Peecha Licenses"
        "2) Section Update plugin"
        "3) Upload: update.zip from this folder"
        ""
        "=== OR web-update (File Manager) ==="
        "1) File Manager -> wp-content/plugins/peecha-license-manager/"
        "2) Upload update.zip and web-update.php from deploy/peecha-license-manager/"
        "3) Open (logged in to wp-admin OR use token URL):"
        $webUpdateUrl
        "4) After OK delete web-update.php and update.zip"
        ""
        "Do NOT upload peecha-license-manager.zip in Plugins -> Add New (often fails to delete old files)."
        ""
        "Fresh install URL (web-install.php):"
        $webInstallUrl
        ""
        "Optional root install:"
        $rootInstallUrl
    )
    Set-Content -LiteralPath $urlFile -Value ($urlText -join "`r`n") -Encoding UTF8

    if ($CreateZip) {
        Write-LmStep "Create plugin ZIP for wp-admin"
        try {
            if (Test-Path -LiteralPath $wpZipPath) {
                Remove-Item -LiteralPath $wpZipPath -Force
            }
            New-PluginFolderZip $pluginDst $wpZipPath 'peecha-license-manager'
            Write-Host "Created: peecha-license-manager.zip (Linux-safe paths)" -ForegroundColor Green
            Copy-Item -LiteralPath $wpZipPath -Destination $wpZipLegacy -Force
            Write-Host "Created: peecha-license-manager-wp.zip (legacy copy)" -ForegroundColor DarkGray
        } catch {
            Write-Host "ZIP failed: $($_.Exception.Message)" -ForegroundColor Yellow
            Write-Host "Zip the peecha-license-manager folder manually." -ForegroundColor Yellow
        }
        try {
            New-PluginFlatZip $pluginDst $updateZipPath
            Write-Host "Created: update.zip (for web-update.php)" -ForegroundColor Green
        } catch {
            Write-Host "update.zip failed: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    $version = Get-PluginVersion (Join-Path $pluginDst 'peecha-license-manager.php')

    return [pscustomobject]@{
        DeployDir       = $deployDir
        PluginDst       = $pluginDst
        ZipPath         = $wpZipPath
        UpdateZipPath   = $updateZipPath
        UrlFile         = $urlFile
        Token           = $token
        WebInstallUrl   = $webInstallUrl
        WebUpdateUrl    = $webUpdateUrl
        RootInstallUrl  = $rootInstallUrl
        Version         = $version
    }
}
