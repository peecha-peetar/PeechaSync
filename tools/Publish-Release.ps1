#Requires -Version 5.1
<#
.SYNOPSIS
  One-shot release: build OTA ZIP -> git push -> GitHub release -> peecha.ir FTP mirror.

  First time only: tools\Setup_WP_LicenseDeploy.bat (FTP user/password)
  Then: tools\Run_Release_All.bat
#>
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'wp-license-deploy.local.json'),
    [string]$CommitMessage = '',
    [switch]$SkipGit,
    [switch]$SkipMirror,
    [switch]$SkipGitHubRelease,
    [switch]$NoPrompt,
    [switch]$ForceGitHubRelease,
    [switch]$SkipSetupPortable,
    [switch]$DeployPlugin,
    # Legacy flags
    [switch]$GitOnly,
    [switch]$ClientOnly,
    [switch]$SkipPlugin
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WP-LicensePlugin-Common.ps1')
. (Join-Path $PSScriptRoot 'ClientRelease-Common.ps1')

if ($GitOnly) {
    $SkipMirror = $true
}
if ($ClientOnly) {
    $SkipGit = $true
    $SkipGitHubRelease = $true
    $DeployPlugin = $false
}

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "=== $msg ===" -ForegroundColor Cyan
}

function Wait-VpnHint {
    param(
        [string]$Target,
        [ValidateSet('on', 'off')]
        [string]$Vpn
    )
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host " VPN / VPN" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
    if ($Vpn -eq 'on') {
        Write-Host "Turn VPN ON (v2rayN / Tun ON)" -ForegroundColor Cyan
        Write-Host "VPN را روشن کنید (GitHub + git push)" -ForegroundColor Cyan
    } else {
        Write-Host "Turn VPN OFF (direct Iran hosting)" -ForegroundColor Cyan
        Write-Host "VPN را خاموش کنید (FTP peecha.ir)" -ForegroundColor Cyan
    }
    Write-Host ""
    Write-Host "Next step: $Target" -ForegroundColor White
    Write-Host ""
    if ($NoPrompt) {
        Write-Host "Continuing in 8 seconds ( -NoPrompt ) ..." -ForegroundColor DarkYellow
        Start-Sleep -Seconds 8
        return
    }
    Write-Host "Press Enter when VPN is ready / Enter بزنید..." -ForegroundColor Green
    Read-Host | Out-Null
    Write-Host ""
}

function Test-DeployConfigReady([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw @"
FTP config missing: $path

Run once: tools\Setup_WP_LicenseDeploy.bat
Fill ftpUser and ftpPassword, Save, then run tools\Run_Release_All.bat again.
"@
    }
    $cfg = (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json)
    $user = [string]$cfg.ftpUser
    $pass = [string]$cfg.ftpPassword
    if (-not $user -or $user -match 'YOUR_FTP') {
        throw "ftpUser not set in $path - run Setup_WP_LicenseDeploy.bat and Save."
    }
    if (-not $pass -or $pass -match 'YOUR_FTP') {
        throw "ftpPassword not set in $path - run Setup_WP_LicenseDeploy.bat and Save."
    }
    return $cfg
}

function Get-GitHubRepo([object]$cfg) {
    $repo = if ($cfg.githubRepo) { [string]$cfg.githubRepo } else { 'peecha-peetar/PeechaSync' }
    return $repo.Trim()
}

function Test-GitIdentityReady([string]$Root) {
    Push-Location $Root
    try {
        $name = (git config user.name 2>$null)
        $email = (git config user.email 2>$null)
        if (-not $name -or -not $email) {
            throw @"
هویتِ Git روی این دستگاه تنظیم نشده — git commit بدونِ این دو مورد اجرا نمی‌شه.

یک‌بار این دو خط رو با نام/ایمیلِ خودتون بزنید:
  git config --global user.name "نام شما"
  git config --global user.email "email@example.com"

بعدش دوباره tools\Run_Release_All.bat رو اجرا کنید.
"@
        }
    } finally {
        Pop-Location
    }
}

function Set-GitRemoteToExpectedRepo([string]$Repo) {
    # آدرسِ origin رو خودکار با ریپوی موردِ انتظار (githubRepo تو کانفیگ، یا
    # پیش‌فرضِ peecha-peetar/PeechaSync) تطبیق می‌ده — تا لازم نباشه کاربر
    # هر بار دستی git remote set-url بزنه. اگه از قبل درست باشه، کاری
    # نمی‌کنه؛ فقط وقتی واقعاً به ریپوی دیگه‌ای اشاره کنه اصلاحش می‌کنه.
    if (-not $Repo) { return }
    $expectedUrl = "https://github.com/$Repo.git"
    $current = (git remote get-url origin 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $current) {
        git remote add origin $expectedUrl 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Git: origin remote added -> $expectedUrl" -ForegroundColor Green
        }
        return
    }
    $current = $current.Trim()
    $normalized = ($current -replace '\.git$', '') -replace '^git@github\.com:', 'https://github.com/'
    $normalizedExpected = $expectedUrl -replace '\.git$', ''
    if ($normalized -ne $normalizedExpected) {
        Write-Host "Git: origin remote اشتباهه ($current) - در حالِ اصلاح به $expectedUrl ..." -ForegroundColor Yellow
        git remote set-url origin $expectedUrl
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Git: origin remote اصلاح شد -> $expectedUrl" -ForegroundColor Green
        }
    }
}

function Invoke-GitPublish {
    param(
        [string]$Root,
        [string]$Version,
        [string]$Message,
        [string]$Repo = ''
    )
    Push-Location $Root
    try {
        if (-not (Test-Path -LiteralPath (Join-Path $Root '.git'))) {
            throw "پوشه‌ی .git اینجا نیست ($Root) - یعنی این پوشه یه ریپوی گیت واقعی نیست. اگه پروژه رو جابه‌جا کردید، پوشه‌ی .git رو هم از مسیر قبلی کپی کنید، یا git init/remote رو دستی بزنید."
        }

        Set-GitRemoteToExpectedRepo $Repo

        $dirty = git status --porcelain 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "git status failed (exit $LASTEXITCODE): $dirty"
        }

        if ($dirty) {
            git add -A
            if ($LASTEXITCODE -ne 0) { throw "git add failed (exit $LASTEXITCODE)" }
            if (-not $Message) {
                $Message = "Release v$Version"
            }
            git commit -m $Message
            if ($LASTEXITCODE -ne 0) { throw "git commit failed (exit $LASTEXITCODE)" }
            Write-Host "Git: committed" -ForegroundColor Green
        } else {
            Write-Host "Git: working tree clean (skip commit)" -ForegroundColor DarkGray
        }

        # به‌جای هاردکدکردنِ «main»، همیشه شاخه‌ی فعلیِ محلی رو push می‌کنیم —
        # چون این ریپو ممکنه (مثلاً بعد از یک git init تازه) روی «master»
        # باشه، نه «main»، و push کردنِ نامِ ثابتِ «main» وقتی چنین شاخه‌ای
        # اصلاً محلی وجود نداره با «src refspec main does not match any»
        # شکست می‌خوره.
        $branch = (git rev-parse --abbrev-ref HEAD 2>&1).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $branch -or $branch -eq 'HEAD') {
            throw "تشخیصِ شاخه‌ی فعلیِ git ناموفق بود: $branch"
        }

        git push origin $branch
        if ($LASTEXITCODE -ne 0) {
            throw "git push failed (exit $LASTEXITCODE) - بررسی کنید VPN روشنه، origin به ریپوی درست اشاره می‌کنه (git remote -v)، و به origin/$branch دسترسی دارید."
        }
        Write-Host "Git: pushed origin/$branch" -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

function Publish-GitHubReleaseAsset {
    param(
        [string]$Repo,
        [string]$Version,
        [string]$ZipPath,
        [switch]$Force
    )
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) {
        Write-Host "gh CLI not found - skip GitHub release (install: https://cli.github.com/)" -ForegroundColor Yellow
        return
    }
    $tag = "v$Version"
    $title = "PeechaSync $Version"
    $notes = "Client OTA update. Auto-update via peecha.ir mirror. Manual: portable setup or in-app update check."

    $exists = $false
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        & gh release view $tag --repo $Repo 2>$null | Out-Null
        $exists = ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $prevEap
    }

    if ($exists -and -not $Force) {
        Write-Host "GitHub release $tag already exists - skip create" -ForegroundColor DarkGray
        return
    }
    if ($exists -and $Force) {
        Write-Host "Removing old GitHub release $tag ..."
        & gh release delete $tag --repo $Repo --yes
        if ($LASTEXITCODE -ne 0) {
            throw "gh release delete failed for $tag"
        }
    }

    Write-Host "Creating GitHub release $tag (upload ~210MB, may take several minutes) ..."
    & gh release create $tag --repo $Repo --title $title --notes $notes $ZipPath
    if ($LASTEXITCODE -ne 0) {
        throw "gh release create failed for $tag"
    }
    Write-Host "GitHub release: https://github.com/$Repo/releases/tag/$tag" -ForegroundColor Green
}

function Build-SetupPortablePackage {
    param([string]$Root)
    $setupPs1 = Join-Path $Root 'release\build_setup_package.ps1'
    if (-not (Test-Path -LiteralPath $setupPs1)) {
        throw "Portable setup builder not found: $setupPs1"
    }
    & $setupPs1 -ProjectRoot $Root
    $version = Get-ClientAppVersion $Root
    $outDir = Join-Path $Root 'tools\client-release-deploy'
    $setupName = "PeechaSync-Setup-$version-Portable.zip"
    $setupZip = Join-Path $outDir $setupName
    $latestPortable = Join-Path $outDir 'latest-portable.zip'
    if (-not (Test-Path -LiteralPath $setupZip)) {
        throw "Portable setup ZIP not created: $setupZip"
    }
    return [pscustomobject]@{
        Version        = $version
        SetupZipPath   = $setupZip
        SetupZipName   = $setupName
        LatestPortable = $latestPortable
        OutDir         = $outDir
    }
}

function Write-DeliveryFolder {
    param(
        [string]$Root,
        [string]$Version,
        [object]$OtaPkg,
        [object]$SetupPkg
    )
    $base = Join-Path $Root 'tools\client-release-deploy'
    $deliveryDir = Join-Path $base "DELIVERY-PeechaSync-$Version"
    if (Test-Path -LiteralPath $deliveryDir) {
        Remove-Item -LiteralPath $deliveryDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $deliveryDir -Force | Out-Null
    Copy-Item -LiteralPath $SetupPkg.SetupZipPath -Destination (Join-Path $deliveryDir $SetupPkg.SetupZipName) -Force
    Copy-Item -LiteralPath $OtaPkg.ZipPath -Destination (Join-Path $deliveryDir $OtaPkg.ZipName) -Force
    $readme = @(
        "PeechaSync v$Version"
        ""
        "Customer install (portable): $($SetupPkg.SetupZipName)"
        "  Extract -> Install PeechaSync.bat -> option 1"
        ""
        "OTA update package: $($OtaPkg.ZipName)"
        "  In-app update or peecha.ir mirror after deploy"
        ""
        "Built: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    ) -join "`r`n"
    Set-Content -LiteralPath (Join-Path $deliveryDir 'DELIVERY.txt') -Value $readme -Encoding UTF8
    return $deliveryDir
}

function Test-PeechaMirrorHealth {
    param(
        [string]$SiteUrl,
        [string]$ExpectedVersion
    )
    $base = ($SiteUrl -replace '/$', '').Trim()
    if (-not $base) { $base = 'https://peecha.ir' }
    $url = "$base/wp-json/peecha/v1/health"
    try {
        $r = Invoke-RestMethod -Uri $url -TimeoutSec 20
        $mirror = [string]$r.mirror_version
        $latest = [string]$r.latest_client_version
        Write-Host "peecha.ir health: mirror=$mirror latest=$latest" -ForegroundColor DarkGray
        if ($mirror -eq $ExpectedVersion) {
            Write-Host "Mirror OK: v$ExpectedVersion visible on server" -ForegroundColor Green
        } else {
            Write-Host "Mirror version on server is '$mirror' (expected $ExpectedVersion). Wait 1 min or set wp-admin Latest version." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Could not verify peecha.ir health: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

try {
    $version = Get-ClientAppVersion $ProjectRoot
    Write-Host "PeechaSync release pipeline v$version" -ForegroundColor Cyan
    Write-Host "OTA + portable setup + git + GitHub + FTP mirror" -ForegroundColor DarkGray

    if (-not $SkipGit) {
        Write-Step "0/6 Preflight: git identity"
        Test-GitIdentityReady $ProjectRoot
        Write-Host "Git identity OK" -ForegroundColor Green
    }

    Write-Step "1/6 Build OTA client ZIP"
    $pkg = Build-ClientReleaseZip -ProjectRoot $ProjectRoot -ToolsRoot $PSScriptRoot
    Write-Host "OTA: $($pkg.ZipName) ($([math]::Round((Get-Item $pkg.ZipPath).Length / 1MB, 1)) MB)" -ForegroundColor Green

    $setupPkg = $null
    if (-not $SkipSetupPortable) {
        Write-Step "2/6 Build portable setup ZIP (customer install)"
        $setupPkg = Build-SetupPortablePackage -Root $ProjectRoot
        Write-Host "Setup: $($setupPkg.SetupZipName) ($([math]::Round((Get-Item $setupPkg.SetupZipPath).Length / 1MB, 1)) MB)" -ForegroundColor Green
        $deliveryDir = Write-DeliveryFolder -Root $ProjectRoot -Version $version -OtaPkg $pkg -SetupPkg $setupPkg
        Write-Host "Delivery folder: $deliveryDir" -ForegroundColor Green
    } else {
        Write-Host "Skip portable setup ( -SkipSetupPortable )" -ForegroundColor DarkGray
    }

    $gitOk = $SkipGit  # اگه از اول Skip شده، جزو "مشکل" حساب نشه
    $mirrorOk = $SkipMirror

    $cfg = $null
    if (Test-Path -LiteralPath $ConfigPath) {
        $cfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    $repo = Get-GitHubRepo $cfg

    if (-not $SkipGit) {
        Write-Step "3/6 Git commit + push"
        Wait-VpnHint -Target 'GitHub: git commit + push + release' -Vpn on
        try {
            Invoke-GitPublish -Root $ProjectRoot -Version $version -Message $CommitMessage -Repo $repo
            $gitOk = $true
        } catch {
            Write-Host "GIT PUBLISH FAILED: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "ادامه می‌دیم سراغ FTP، ولی گیت/گیت‌هاب آپدیت نشد." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Skip git ( -SkipGit )" -ForegroundColor DarkGray
    }

    if (-not $SkipGitHubRelease -and -not $SkipGit -and $gitOk) {
        Write-Step "4/6 GitHub release asset"
        Publish-GitHubReleaseAsset -Repo $repo -Version $version -ZipPath $pkg.ZipPath -Force:$ForceGitHubRelease
    } else {
        Write-Host "Skip GitHub release" -ForegroundColor DarkGray
    }

    if (-not $SkipMirror) {
        Write-Step "5/6 FTP mirror on peecha.ir"
        $cfg = Test-DeployConfigReady $ConfigPath
        Wait-VpnHint -Target 'peecha.ir: FTP upload mirror' -Vpn off

        if ($DeployPlugin) {
            & (Join-Path $PSScriptRoot 'Deploy-WP-LicensePlugin.ps1') `
                -ProjectRoot $ProjectRoot -ConfigPath $ConfigPath
            & (Join-Path $PSScriptRoot 'Deploy-ClientUpdateMirror.ps1') `
                -ProjectRoot $ProjectRoot -ConfigPath $ConfigPath -SkipBuild
        } else {
            & (Join-Path $PSScriptRoot 'Deploy-ClientUpdateMirror.ps1') `
                -ProjectRoot $ProjectRoot -ConfigPath $ConfigPath -SkipBuild
        }
        if ($LASTEXITCODE -eq 0) {
            $mirrorOk = $true
        } else {
            Write-Host "FTP MIRROR FAILED (exit $LASTEXITCODE) - فایل رو دستی آپلود کنید یا رمز FTP رو چک کنید." -ForegroundColor Red
        }

        Write-Step "6/6 Verify mirror"
        $siteUrl = if ($cfg.siteUrl) { [string]$cfg.siteUrl } else { 'https://peecha.ir' }
        Test-PeechaMirrorHealth -SiteUrl $siteUrl -ExpectedVersion $version
    } else {
        Write-Host "Skip FTP mirror ( -SkipMirror )" -ForegroundColor DarkGray
    }

    Write-Host ""
    if ($gitOk -and $mirrorOk) {
        Write-Host "RELEASE DONE v$version" -ForegroundColor Green
    } else {
        Write-Host "RELEASE PARTIAL v$version - بعضی مرحله‌ها ناموفق بودن، پایین رو ببینید" -ForegroundColor Yellow
        if (-not $gitOk) { Write-Host "  [FAILED] Git/GitHub منتشر نشد" -ForegroundColor Red }
        if (-not $mirrorOk) { Write-Host "  [FAILED] آپلود FTP روی peecha.ir ناموفق بود" -ForegroundColor Red }
    }
    Write-Host "  OTA (mirror/update): $($pkg.ZipPath)" -ForegroundColor White
    if ($setupPkg) {
        Write-Host "  Setup (customer):    $($setupPkg.SetupZipPath)" -ForegroundColor White
        Write-Host "  Delivery folder:     tools\client-release-deploy\DELIVERY-PeechaSync-$version" -ForegroundColor White
    }
    if ($gitOk -and -not $SkipGit) {
        Write-Host "  GitHub: peecha-peetar/PeechaSync tag v$version" -ForegroundColor White
    }
    if ($mirrorOk -and -not $SkipMirror) {
        Write-Host "  Mirror: wp-content/uploads/peecha-sync-updates/$($pkg.ZipName)" -ForegroundColor White
    }
    Write-Host ""
    Write-Host "Send customer the Setup ZIP from DELIVERY folder." -ForegroundColor DarkGray
} catch {
    Write-Host ""
    Write-Host "RELEASE FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Partial recovery:" -ForegroundColor Yellow
    Write-Host "  VPN ON  + tools\Run_Publish_Release.bat -GitOnly" -ForegroundColor Yellow
    Write-Host "  VPN OFF + tools\Run_Publish_Release.bat -ClientOnly -SkipGit -SkipGitHubRelease" -ForegroundColor Yellow
    exit 1
}
