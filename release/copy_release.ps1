#Requires -Version 5.1
<#
.SYNOPSIS
  Creates a clean distributable copy of PeechaSync (no secrets, caches, or dev artifacts).
#>
param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TargetRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) "PeechaSync-Release")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $SourceRoot)) {
    throw "Source not found: $SourceRoot"
}

$excludeDirs = @(
    ".git", ".github", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    "build", "dist", ".idea", ".vscode", ".cursor", "node_modules", "release", "installer",
    "DATA3", "wordpress-plugin", "tools", "category_images", "product_images",
    "client-release-deploy", "wp-license-deploy"
)
$excludeFiles = @(
    "*.pyc", "*.pyo", "*.log", "sync_key.key", "secure_config.bin", "secure_config.json",
    "license.json", "license.json.example", "*.spec",
    "product_woo_map.json", "product_woo_map_meta.json",
    "category_map.json", "category_images_map.json", "product_images_map.json",
    "Force-Git-Sync.bat", "Fix-Git-Update.bat", "Fix-Skip-Git.bat",
    "Run_Deploy_WP_LicensePlugin.bat", "Run_Sync_And_Deploy_Plugin.bat", "Repair-RunBat.bat",
    "peecha_launcher.py", "settings_tab.py", "tab_auto_sync.py", "tab_categories.py",
    "tab_products.py", "tab_variations.py", "update_variations.py", "wc_sync_helper.py",
    "cd", "cls", "git", "FETCH_HEAD"
)

Write-Host "Source : $SourceRoot"
Write-Host "Target : $TargetRoot"

if (Test-Path $TargetRoot) {
    Write-Host "Removing existing target..."
    Remove-Item -LiteralPath $TargetRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $TargetRoot -Force | Out-Null

function Should-SkipDir([string]$Name) {
    return $excludeDirs -contains $Name
}

function Should-SkipFile([string]$Name) {
    foreach ($pattern in $excludeFiles) {
        if ($Name -like $pattern) { return $true }
    }
    return $false
}

function Copy-Tree([string]$Src, [string]$Dst) {
    New-Item -ItemType Directory -Path $Dst -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $Src -Force) {
        if ($item.PSIsContainer) {
            if (Should-SkipDir $item.Name) { continue }
            Copy-Tree $item.FullName (Join-Path $Dst $item.Name)
        }
        else {
            if (Should-SkipFile $item.Name) { continue }
            Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $Dst $item.Name) -Force
        }
    }
}

Copy-Tree $SourceRoot $TargetRoot

$launcherDir = Join-Path $SourceRoot "release\installer\templates\_setup\engine\app"
if (Test-Path -LiteralPath $launcherDir) {
        foreach ($name in @(
            'Run-PeechaSync.bat', 'launch-gui.ps1', 'launch-gui.cmd', 'set-python-env.bat',
            'test-import.ps1', 'show-startup-error.bat', 'show-user-message.ps1',
            'peecha-version-refresh.ps1', 'Apply-ClientUpdate.ps1',
            'Force-CleanProgramFiles.ps1', 'Assert-InstalledVersion.ps1',
            'peecha-apply-cached-update.ps1', 'Apply-CachedUpdate.bat'
        )) {
        $src = Join-Path $launcherDir $name
        if (Test-Path -LiteralPath $src) {
            Copy-Item -LiteralPath $src -Destination (Join-Path $TargetRoot $name) -Force
        }
    }
}

# Marker: run.bat skips git fetch on customer installs
$version = "unknown"
$appVersionPath = Join-Path $SourceRoot "sync_app\core\app_version.py"
if (Test-Path -LiteralPath $appVersionPath) {
    foreach ($line in Get-Content -LiteralPath $appVersionPath -Encoding UTF8) {
        if ($line -match '_BUILTIN_VERSION\s*=\s*"(?<ver>[0-9.]+)"') {
            $version = $Matches['ver'].Trim()
            break
        }
        if ($line -match 'APP_VERSION\s*=\s*"(?<ver>[0-9.]+)"') {
            $version = $Matches['ver'].Trim()
            break
        }
    }
}
if ($version -ne 'unknown') {
    Set-Content -LiteralPath (Join-Path $TargetRoot 'VERSION.txt') -Value $version -Encoding ASCII
}
@"
PeechaSync release package
Version: $version
Git auto-update disabled — use in-app update from peecha.ir
"@ | Set-Content -LiteralPath (Join-Path $TargetRoot ".peecha-release") -Encoding UTF8

# Ensure release helper folders exist
$null = New-Item -ItemType Directory -Path (Join-Path $TargetRoot "release") -Force
Copy-Item -LiteralPath $PSScriptRoot -Destination (Join-Path $TargetRoot "release") -Recurse -Force

Write-Host ""
Write-Host "Clean release copy created successfully."
Write-Host $TargetRoot
