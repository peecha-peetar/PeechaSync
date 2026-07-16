#Requires -Version 5.1
# PeechaSync Release Wizard (ASCII script + UTF-8 JSON strings)
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [ValidateSet('auto', 'en', 'fa')]
    [string]$Lang = 'auto'
)

$ErrorActionPreference = 'Continue'

function Resolve-WizardLanguage {
    param([string]$Requested)
    if ($Requested -eq 'en' -or $Requested -eq 'fa') {
        return $Requested
    }
    if ($env:WT_SESSION -or $env:WT_PROFILE_ID) {
        return 'fa'
    }
    return 'en'
}

function Initialize-WizardConsole {
    param([string]$Language)
    try {
        if ($Language -eq 'fa') {
            chcp 65001 | Out-Null
        } else {
            chcp 437 | Out-Null
        }
    } catch {}
    try {
        if ($Language -eq 'fa') {
            [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
            [Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
        } else {
            [Console]::OutputEncoding = [System.Text.Encoding]::Default
            [Console]::InputEncoding = [System.Text.Encoding]::Default
        }
        $global:OutputEncoding = [Console]::OutputEncoding
    } catch {}
}

function Import-WizardMessages {
    param([string]$Language)
    $fileName = if ($Language -eq 'fa') { 'Release-Wizard.fa.json' } else { 'Release-Wizard.en.json' }
    $jsonPath = Join-Path $PSScriptRoot $fileName
    if (-not (Test-Path -LiteralPath $jsonPath)) {
        throw "Messages file not found: $jsonPath"
    }
    $raw = Get-Content -LiteralPath $jsonPath -Raw -Encoding UTF8
    return ($raw | ConvertFrom-Json)
}

function Show-LanguageBanner {
    param([string]$Language)
    if ($Language -eq 'fa') {
        Write-Host '  UI: Persian (Windows Terminal / UTF-8)' -ForegroundColor DarkGray
    } else {
        Write-Host '  UI: English (classic CMD cannot show Persian)' -ForegroundColor DarkGray
        Write-Host '  Tip: install Windows Terminal for Persian UI' -ForegroundColor DarkGray
    }
    Write-Host ''
}

function Expand-StepText {
    param(
        [string]$Template,
        $VersionInfo
    )
    if (-not $Template) { return '' }
    return $Template.Replace('{app}', $VersionInfo.App).
        Replace('{plugin}', $VersionInfo.Plugin).
        Replace('{setupZip}', $VersionInfo.SetupZipName).
        Replace('{clientZip}', $VersionInfo.ClientZipName)
}

$script:UiLang = Resolve-WizardLanguage $Lang
Initialize-WizardConsole $script:UiLang
$script:Msg = Import-WizardMessages $script:UiLang

. (Join-Path $PSScriptRoot 'ClientRelease-Common.ps1')
. (Join-Path $PSScriptRoot 'WP-LicensePlugin-Common.ps1')

$script:ToolsRoot = $PSScriptRoot
$script:DeployDir = Join-Path $ToolsRoot 'client-release-deploy'
$script:FailCount = 0
$script:SkipCount = 0

function Get-PluginVersionFromProject {
    $main = Join-Path $ProjectRoot 'wordpress-plugin\peecha-license-manager\peecha-license-manager.php'
    if (-not (Test-Path -LiteralPath $main)) { return '?' }
    return Get-PluginVersion $main
}

function Get-VersionInfo {
    $app = try { Get-ClientAppVersion $ProjectRoot } catch { '?' }
    $plugin = Get-PluginVersionFromProject
    [pscustomobject]@{
        App           = $app
        Plugin        = $plugin
        SetupZipName  = "PeechaSync-Setup-$app-Portable.zip"
        ClientZipName = "PeechaSync-$app.zip"
        SetupZipPath  = Join-Path $script:DeployDir "PeechaSync-Setup-$app-Portable.zip"
        ClientZipPath = Join-Path $script:DeployDir "PeechaSync-$app.zip"
        UpdateZipPath = Join-Path $ToolsRoot 'wp-license-deploy\update.zip'
    }
}

function Write-Bar {
    param([string]$Text, [string]$Color = 'Cyan')
    $line = ('=' * 62)
    Write-Host $line -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor $Color
    Write-Host $line -ForegroundColor DarkGray
}

function Write-FileStatus {
    param([string]$Path)
    if (-not $Path) { return }
    $leaf = Split-Path -Leaf $Path
    if (Test-Path -LiteralPath $Path) {
        $kb = [math]::Round((Get-Item -LiteralPath $Path).Length / 1KB, 1)
        Write-Host "  $($script:Msg.fileLabel) " -NoNewline -ForegroundColor DarkGray
        Write-Host $leaf -ForegroundColor Green -NoNewline
        Write-Host " ($kb KB - $($script:Msg.fileExists))" -ForegroundColor DarkGreen
    } else {
        Write-Host "  $($script:Msg.fileLabel) " -NoNewline -ForegroundColor DarkGray
        Write-Host $leaf -ForegroundColor Yellow -NoNewline
        Write-Host " ($($script:Msg.fileMissing))" -ForegroundColor DarkYellow
    }
}

function Show-VersionPanel {
    param($V)
    Write-Host ''
    Write-Host "  $($script:Msg.appVersion)    " -NoNewline -ForegroundColor DarkGray
    Write-Host $V.App -ForegroundColor White
    Write-Host "  $($script:Msg.pluginVersion)    " -NoNewline -ForegroundColor DarkGray
    Write-Host $V.Plugin -ForegroundColor White
    Write-Host "  $($script:Msg.zipSetup)         " -NoNewline -ForegroundColor DarkGray
    Write-Host $V.SetupZipName -ForegroundColor DarkCyan
    Write-Host "  $($script:Msg.zipUpdate)   " -NoNewline -ForegroundColor DarkGray
    Write-Host $V.ClientZipName -ForegroundColor DarkCyan
    Write-Host ''
}

function Confirm-Step {
    param([string]$Prompt)
    if (-not $Prompt) { $Prompt = $script:Msg.confirmDefault }
    Write-Host ''
    $ans = (Read-Host "$Prompt  [Y/N]").Trim()
    return $ans -match '^(y|Y|yes|a)$'
}

function Pause-Continue {
    Write-Host ''
    Read-Host $script:Msg.pressEnter | Out-Null
}

function Invoke-Step {
    param(
        [string]$Title,
        [scriptblock]$Action
    )
    Write-Host ''
    Write-Host ">>> $Title" -ForegroundColor Cyan
    Write-Host ''
    try {
        & $Action
        if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            throw "exit code $LASTEXITCODE"
        }
        Write-Host ''
        Write-Host "  $($script:Msg.done)" -ForegroundColor Green
        return $true
    } catch {
        $script:FailCount++
        Write-Host ''
        Write-Host "  $($script:Msg.error) $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

function Test-FtpConfig {
    $cfg = Join-Path $ToolsRoot 'wp-license-deploy.local.json'
    if (Test-Path -LiteralPath $cfg) { return $true }
    Write-Host ''
    Write-Host "  $($script:Msg.ftpMissing)" -ForegroundColor Yellow
    Write-Host '  tools\Setup_WP_LicenseDeploy.bat' -ForegroundColor White
    $script:FailCount++
    return $false
}

function Show-StepScreen {
    param(
        [string]$StepNo,
        [string]$TitleFa,
        [string]$HintFa = '',
        $VersionInfo,
        [string]$FilePath = ''
    )
    Clear-Host
    Write-Bar $script:Msg.wizardTitle
    Write-Host "  $($script:Msg.stepLabel) $StepNo" -ForegroundColor Yellow
    Write-Host ''
    Write-Host "  $TitleFa" -ForegroundColor White
    if ($HintFa) {
        Write-Host "  $HintFa" -ForegroundColor DarkGray
    }
    Write-Host ''
    if ($FilePath) { Write-FileStatus $FilePath }
    Show-VersionPanel $VersionInfo
}

function Run-GitSync {
    $bat = Join-Path $ProjectRoot 'Force-Git-Sync.bat'
    Invoke-Step $script:Msg.runTitles.git { cmd /c "`"$bat`"" } | Out-Null
}

function Run-PortableZip {
    Invoke-Step $script:Msg.runTitles.portable {
        & (Join-Path $ProjectRoot 'release\build_setup_package.ps1')
    } | Out-Null
}

function Run-ClientZip {
    Invoke-Step $script:Msg.runTitles.client {
        & (Join-Path $ToolsRoot 'Deploy-ClientUpdateMirror.ps1') -BuildOnly
    } | Out-Null
}

function Run-UpdateZip {
    Invoke-Step $script:Msg.runTitles.update {
        & (Join-Path $ToolsRoot 'Make-UpdateZip.ps1')
    } | Out-Null
    $dir = Join-Path $ToolsRoot 'wp-license-deploy'
    if (Test-Path -LiteralPath $dir) { Start-Process explorer.exe $dir }
}

function Run-PluginFtp {
    if (-not (Test-FtpConfig)) { return }
    Invoke-Step $script:Msg.runTitles.pluginFtp {
        & (Join-Path $ToolsRoot 'Deploy-WP-LicensePlugin.ps1')
    } | Out-Null
}

function Run-ClientMirrorFtp {
    if (-not (Test-FtpConfig)) { return }
    Invoke-Step $script:Msg.runTitles.mirrorFtp {
        & (Join-Path $ToolsRoot 'Deploy-ClientUpdateMirror.ps1')
    } | Out-Null
}

function Run-CombinedFtp {
    if (-not (Test-FtpConfig)) { return }
    Invoke-Step $script:Msg.runTitles.combinedFtp {
        & (Join-Path $ToolsRoot 'Deploy-WP-LicensePlugin.ps1') -AlsoDeployClient
    } | Out-Null
}

function Run-FullPublish {
    Write-Host "  $($script:Msg.vpnGithub)" -ForegroundColor Yellow
    Write-Host "  $($script:Msg.vpnFtp)" -ForegroundColor Yellow
    Pause-Continue
    Invoke-Step $script:Msg.runTitles.publish {
        & (Join-Path $ToolsRoot 'Publish-Release.ps1')
    } | Out-Null
}

function Get-StepDefinitions {
    param($V)
    $m = $script:Msg.steps
    @(
        @{ Key = '1'; Title = Expand-StepText $m.'1'.title $V; Hint = Expand-StepText $m.'1'.hint $V; File = ''; Action = { Run-GitSync } },
        @{ Key = '2'; Title = Expand-StepText $m.'2'.title $V; Hint = Expand-StepText $m.'2'.hint $V; File = $V.SetupZipPath; Action = { Run-PortableZip } },
        @{ Key = '3'; Title = Expand-StepText $m.'3'.title $V; Hint = Expand-StepText $m.'3'.hint $V; File = $V.ClientZipPath; Action = { Run-ClientZip } },
        @{ Key = '4'; Title = Expand-StepText $m.'4'.title $V; Hint = Expand-StepText $m.'4'.hint $V; File = $V.UpdateZipPath; Action = { Run-UpdateZip } },
        @{ Key = '5'; Title = Expand-StepText $m.'5'.title $V; Hint = Expand-StepText $m.'5'.hint $V; File = ''; Action = { Run-PluginFtp } },
        @{ Key = '6'; Title = Expand-StepText $m.'6'.title $V; Hint = Expand-StepText $m.'6'.hint $V; File = $V.ClientZipPath; Action = { Run-ClientMirrorFtp } },
        @{ Key = '7'; Title = Expand-StepText $m.'7'.title $V; Hint = Expand-StepText $m.'7'.hint $V; File = $V.ClientZipPath; Action = { Run-CombinedFtp } },
        @{ Key = '8'; Title = Expand-StepText $m.'8'.title $V; Hint = Expand-StepText $m.'8'.hint $V; File = ''; Action = { Run-FullPublish } }
    )
}

function Show-MainMenu {
    param($V, $Steps)
    Clear-Host
    Write-Bar $script:Msg.wizardTitle 'Green'
    Show-LanguageBanner $script:UiLang
    Write-Host "  $($script:Msg.vpnHint)" -ForegroundColor DarkGray
    Write-Host ''
    Show-VersionPanel $V
    Write-Host "  $($script:Msg.menu)" -ForegroundColor Cyan
    foreach ($s in $Steps) {
        Write-Host "    [$($s.Key)] $($s.Title)" -ForegroundColor White
    }
    Write-Host ''
    Write-Host "    [A] $($script:Msg.menuAll)" -ForegroundColor Yellow
    Write-Host "    [0] $($script:Msg.menuExit)" -ForegroundColor DarkGray
    Write-Host ''
}

function Run-SequentialWizard {
    param($Steps)
    foreach ($s in $Steps) {
        $V = Get-VersionInfo
        Show-StepScreen -StepNo $s.Key -TitleFa $s.Title -HintFa $s.Hint -VersionInfo $V -FilePath $s.File
        $prompt = $script:Msg.confirmStep -f $s.Key
        if (Confirm-Step $prompt) {
            & $s.Action
        } else {
            $script:SkipCount++
            Write-Host "  $($script:Msg.skipped)" -ForegroundColor DarkYellow
        }
        Pause-Continue
    }
}

function Run-SingleStep {
    param($Steps, [string]$Key)
    $s = $Steps | Where-Object { $_.Key -eq $Key } | Select-Object -First 1
    if (-not $s) {
        Write-Host "  $($script:Msg.invalidOption)" -ForegroundColor Red
        return
    }
    $V = Get-VersionInfo
    Show-StepScreen -StepNo $s.Key -TitleFa $s.Title -HintFa $s.Hint -VersionInfo $V -FilePath $s.File
    if (Confirm-Step $script:Msg.confirmRun) {
        & $s.Action
    } else {
        Write-Host "  $($script:Msg.skipped)" -ForegroundColor DarkYellow
    }
    Pause-Continue
}

try {
    while ($true) {
        $V = Get-VersionInfo
        $steps = Get-StepDefinitions $V
        Show-MainMenu $V $steps
        $choice = (Read-Host $script:Msg.choicePrompt).Trim()

        if ($choice -eq '0') { break }
        if ($choice -match '^(a|A)$') {
            Run-SequentialWizard $steps
            continue
        }
        if ($choice -match '^[1-8]$') {
            Run-SingleStep $steps $choice
            continue
        }
        Write-Host "  $($script:Msg.invalidChoice)" -ForegroundColor Red
        Pause-Continue
    }

    Clear-Host
    Write-Bar $script:Msg.endTitle 'Green'
    $V = Get-VersionInfo
    Show-VersionPanel $V
    if ($script:FailCount -gt 0) {
        Write-Host "  $($script:FailCount) $($script:Msg.stepsFailed)" -ForegroundColor Red
        exit 1
    }
    Write-Host "  $($script:Msg.allDone)" -ForegroundColor Green
    if ($script:SkipCount -gt 0) {
        Write-Host "  $($script:SkipCount) $($script:Msg.stepsSkipped)" -ForegroundColor DarkYellow
    }
    exit 0
} catch {
    Write-Host ''
    Write-Host "FATAL: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
