# PeechaSync setup
param(
    [ValidateSet('install', 'menu', 'launcher')]
    [string]$Mode = 'launcher'
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$lib = $PSScriptRoot
$pkgRoot = Split-Path -Parent $lib
$packageRoot = Split-Path -Parent $pkgRoot

$Theme = @{
    Primary  = [System.Drawing.Color]::FromArgb(2, 0, 37)
    Hover    = [System.Drawing.Color]::FromArgb(23, 19, 79)
    Soft     = [System.Drawing.Color]::FromArgb(236, 235, 255)
    Border   = [System.Drawing.Color]::FromArgb(201, 199, 255)
    Text     = [System.Drawing.Color]::FromArgb(15, 23, 42)
    SubText  = [System.Drawing.Color]::FromArgb(71, 85, 105)
    White    = [System.Drawing.Color]::White
}

function Get-AppVersion {
    $vf = Join-Path $pkgRoot 'VERSION.txt'
    if (Test-Path -LiteralPath $vf) {
        return (Get-Content -LiteralPath $vf -Raw).Trim()
    }
    return '?'
}

function Get-InstallDir {
    $locFile = Join-Path $env:LOCALAPPDATA 'PeechaSync\install.loc'
    if (Test-Path -LiteralPath $locFile) {
        $raw = (Get-Content -LiteralPath $locFile -Raw).Trim()
        return $raw.TrimStart([char]0xFEFF)
    }
    return 'C:\PeechaSync'
}

function Install-DesktopShortcut {
    param([string]$InstallDir)

    $targetBat = Join-Path $InstallDir 'Run-PeechaSync.bat'
    if (-not (Test-Path -LiteralPath $targetBat)) {
        return $false
    }

    $shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PeechaSync.lnk'
    $icon = Join-Path $InstallDir 'PeechaSync.ico'
    if (-not (Test-Path -LiteralPath $icon)) {
        $icon = Join-Path $pkgRoot 'PeechaSync.ico'
    }

    & (Join-Path $lib 'remove-shortcuts.ps1') | Out-Null

    $env:SC_SHORTCUT = $shortcut
    $env:SC_TARGET_BAT = $targetBat
    $env:SC_WORKING_DIR = $InstallDir
    if (Test-Path -LiteralPath $icon) {
        $env:SC_ICON_FILE = $icon
    } else {
        $env:SC_ICON_FILE = ''
    }

    & (Join-Path $lib 'create-shortcut.ps1')
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    return (Test-Path -LiteralPath $shortcut)
}

function Start-PeechaApp {
    param([string]$InstallDir)

    $shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PeechaSync.lnk'
    if (Test-Path -LiteralPath $shortcut) {
        Start-Process -FilePath $shortcut | Out-Null
        return
    }

    $vbs = Join-Path $InstallDir 'Launch-PeechaSync.vbs'
    if (Test-Path -LiteralPath $vbs) {
        $wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
        Start-Process -FilePath $wscript -ArgumentList "`"$vbs`"" -WorkingDirectory $InstallDir | Out-Null
        return
    }

    $runner = Join-Path $InstallDir 'Run-PeechaSync.bat'
    if (-not (Test-Path -LiteralPath $runner)) {
        return
    }
    Start-Process -FilePath $env:ComSpec `
        -ArgumentList '/c', "`"$runner`"" `
        -WorkingDirectory $InstallDir `
        -WindowStyle Hidden | Out-Null
}

function Show-ErrorBox {
    param([string]$En, [string]$Fa)
    $text = "$En`n`n$Fa"
    & (Join-Path $lib 'show-message.ps1') -Title 'PeechaSync' -Text $text -Icon Error | Out-Null
}

function Show-InfoBox {
    param([string]$En, [string]$Fa)
    $text = "$En`n`n$Fa"
    & (Join-Path $lib 'show-message.ps1') -Title 'PeechaSync' -Text $text -Icon Information | Out-Null
}

function Show-SetupDetails {
    $ver = Get-AppVersion
    $text = @"
نسخه $ver

با زدن 1 فایل‌ها نصب یا بروز می‌شود، شورتکات دسکتاپ ساخته می‌شود و PeechaSync اجرا می‌شود.
ویندوز 10/11. Python داخل ZIP است — نصب جدا لازم نیست.
برای نصب اول یا تعمیر پکیج‌ها اینترنت لازم نیست (پکیج‌ها داخل ZIP هستند).

Version $ver

Press 1 to install or update, fix the desktop shortcut, and run PeechaSync.
Requires Windows 10/11. Python is bundled in the installer ZIP.
Packages are bundled offline in the installer ZIP.
"@
    [System.Windows.Forms.MessageBox]::Show(
        $text,
        'PeechaSync',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}

function Set-ActionButtonSize {
    param($Button, [int]$Height = 58)
    $Button.Size = New-Object System.Drawing.Size(388, $Height)
    $Button.Padding = New-Object System.Windows.Forms.Padding(16, 10, 12, 10)
}

function Set-PrimaryButtonStyle {
    param($Button)
    $Button.FlatStyle = 'Flat'
    $Button.FlatAppearance.BorderSize = 0
    $Button.BackColor = $Theme.Primary
    $Button.ForeColor = $Theme.White
    $Button.Font = New-Object System.Drawing.Font('Segoe UI', 10.5, [System.Drawing.FontStyle]::Bold)
    $Button.Cursor = [System.Windows.Forms.Cursors]::Hand
    $Button.Add_MouseEnter({ $this.BackColor = $Theme.Hover })
    $Button.Add_MouseLeave({ $this.BackColor = $Theme.Primary })
}

function Set-SecondaryButtonStyle {
    param($Button)
    $Button.FlatStyle = 'Flat'
    $Button.FlatAppearance.BorderSize = 1
    $Button.FlatAppearance.BorderColor = $Theme.Border
    $Button.BackColor = $Theme.White
    $Button.ForeColor = $Theme.Text
    $Button.Cursor = [System.Windows.Forms.Cursors]::Hand
    $Button.Add_MouseEnter({ $this.BackColor = $Theme.Soft })
    $Button.Add_MouseLeave({ $this.BackColor = $Theme.White })
}

function Test-NeedDeps {
    $installDir = Get-InstallDir
    foreach ($rel in @('python\python.exe', '.venv\Scripts\python.exe')) {
        $vpy = Join-Path $installDir $rel
        if (-not (Test-Path -LiteralPath $vpy)) { continue }
        & $vpy -c "import PyQt5, pyodbc, requests, woocommerce, cryptography, psutil" 2>$null
        if ($LASTEXITCODE -eq 0) { return $false }
        return $true
    }
    return $true
}

function Test-HasBundledPython {
    $p = Join-Path $pkgRoot 'engine\runtime\python\python.exe'
    return (Test-Path -LiteralPath $p)
}

function Test-HasOfflinePackages {
    $pkg = Join-Path $pkgRoot 'engine\packages'
    if (-not (Test-Path -LiteralPath $pkg)) { return $false }
    return [bool](Get-ChildItem -LiteralPath $pkg -Filter '*.whl' -File -ErrorAction SilentlyContinue)
}

function Invoke-Install {
    if ((Test-NeedDeps) -and (-not (Test-HasOfflinePackages)) -and (-not (Test-HasBundledPython))) {
        Show-ErrorBox `
            -En 'Offline packages are missing from this installer. Re-extract the full ZIP.' `
            -Fa 'پکیج‌های آفلاین داخل نصاب نیست. ZIP را کامل Extract کنید.'
        return 12
    }

    & (Join-Path $lib 'kill-peecha-processes.bat') | Out-Null

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'PeechaSync'
    $form.Size = New-Object System.Drawing.Size(480, 220)
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.BackColor = $Theme.Soft
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
    $form.TopMost = $true

    $header = New-Object System.Windows.Forms.Panel
    $header.Size = New-Object System.Drawing.Size(464, 44)
    $header.Location = New-Object System.Drawing.Point(0, 0)
    $header.BackColor = $Theme.Primary
    $form.Controls.Add($header)

    $headerLbl = New-Object System.Windows.Forms.Label
    $headerLbl.AutoSize = $false
    $headerLbl.Size = New-Object System.Drawing.Size(464, 44)
    $headerLbl.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $headerLbl.ForeColor = $Theme.White
    $headerLbl.Font = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
    $headerLbl.Text = 'PeechaSync Setup'
    $header.Controls.Add($headerLbl)

    $label = New-Object System.Windows.Forms.Label
    $label.AutoSize = $false
    $label.Size = New-Object System.Drawing.Size(440, 48)
    $label.Location = New-Object System.Drawing.Point(20, 58)
    $label.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $label.ForeColor = $Theme.Text
    $label.Text = "Installing...`nدر حال نصب..."
    $form.Controls.Add($label)

    $stepLbl = New-Object System.Windows.Forms.Label
    $stepLbl.AutoSize = $false
    $stepLbl.Size = New-Object System.Drawing.Size(440, 22)
    $stepLbl.Location = New-Object System.Drawing.Point(20, 108)
    $stepLbl.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $stepLbl.ForeColor = $Theme.SubText
    $stepLbl.Font = New-Object System.Drawing.Font('Segoe UI', 9)
    $stepLbl.Text = ''
    $form.Controls.Add($stepLbl)

    $bar = New-Object System.Windows.Forms.ProgressBar
    $bar.Style = 'Marquee'
    $bar.MarqueeAnimationSpeed = 30
    $bar.Size = New-Object System.Drawing.Size(440, 18)
    $bar.Location = New-Object System.Drawing.Point(20, 136)
    $form.Controls.Add($bar)

    $progressFile = Join-Path $env:LOCALAPPDATA 'PeechaSync\install-progress.txt'
    $stepMap = @{
        'starting'      = 'Starting... / شروع'
        'clean-old'     = 'Removing old program files... / حذف فایل‌های قبلی برنامه'
        'copy-app'      = 'Copying app files... / کپی فایل‌ها'
        'copy-packages' = 'Copying packages... / کپی پکیج‌ها'
        'copy-python'   = 'Copying Python (may take a few minutes)... / کپی پایتون'
        'deps'          = 'Checking packages... / بررسی پکیج‌ها'
        'finalize'      = 'Finishing... / اتمام'
        'done'          = 'Done / تمام'
    }

    $form.Add_Shown({ $form.Activate() })
    $form.Show()
    [System.Windows.Forms.Application]::DoEvents()

    $bat = Join-Path $lib 'install-app.bat'
    $proc = Start-Process -FilePath $env:ComSpec `
        -ArgumentList '/c', "`"$bat`"" `
        -WorkingDirectory $lib `
        -WindowStyle Hidden `
        -PassThru

    $deadline = [datetime]::UtcNow.AddMinutes(20)
    while (-not $proc.HasExited) {
        if (Test-Path -LiteralPath $progressFile) {
            $step = (Get-Content -LiteralPath $progressFile -Tail 1 -ErrorAction SilentlyContinue)
            if ($step -and $stepMap.ContainsKey($step)) {
                $stepLbl.Text = $stepMap[$step]
            }
        }
        [System.Windows.Forms.Application]::DoEvents()
        if ([datetime]::UtcNow -gt $deadline) {
            try { $proc.Kill() } catch {}
            $form.Close()
            $form.Dispose()
            Show-ErrorBox `
                -En 'Install timed out. Check install-errors.log in AppData\PeechaSync.' `
                -Fa 'نصب خیلی طول کشید. فایل install-errors.log در AppData\PeechaSync را بفرستید.'
            return 13
        }
        Start-Sleep -Milliseconds 200
    }
    $rc = $proc.ExitCode

    $form.Close()
    $form.Dispose()

    if ($rc -eq 12) {
        return 12
    }
    if ($rc -eq 11) {
        Show-ErrorBox `
            -En 'Package install failed. Run Install PeechaSync.bat again from the extracted ZIP folder.' `
            -Fa 'نصب پکیج‌ها انجام نشد. دوباره Install PeechaSync.bat را از همان پوشه Extract‌شده بزنید.'
        return $rc
    }
    if ($rc -ne 0) {
        $logHint = Join-Path $env:LOCALAPPDATA 'PeechaSync\install-errors.log'
        $logTail = ''
        if (Test-Path -LiteralPath $logHint) {
            $logTail = (Get-Content -LiteralPath $logHint -Tail 8 -ErrorAction SilentlyContinue) -join "`n"
        }
        $stepHint = ''
        if (Test-Path -LiteralPath $progressFile) {
            $lastStep = (Get-Content -LiteralPath $progressFile -Tail 1 -ErrorAction SilentlyContinue)
            if ($lastStep) { $stepHint = "Step: $lastStep / مرحله: $lastStep`n`n" }
        }
        $targetDir = Get-InstallDir
        Show-ErrorBox `
            -En ($stepHint + "Install failed (code $rc). Target: $targetDir`n`nClose PeechaSync and run Install Console.bat to see details.`n`nLog:`n$logTail") `
            -Fa ($stepHint + "نصب انجام نشد (کد $rc). مسیر: $targetDir`n`nبرنامه را ببندید. Install Console.bat را بزنید.`n`nلاگ:`n$logTail")
        return $rc
    }

    $installDir = Get-InstallDir
    $launcherPyc = Join-Path $installDir 'sync_app\core\peecha_launcher.pyc'
    $runnerBat = Join-Path $installDir 'Run-PeechaSync.bat'
    if (-not ((Test-Path -LiteralPath $launcherPyc) -and (Test-Path -LiteralPath $runnerBat))) {
        Show-ErrorBox `
            -En "Install reported success but files are missing in:`n$installDir`n`nTry Install Console.bat (shows errors)." `
            -Fa "نصب تمام شد ولی فایل‌ها در این مسیر نیست:`n$installDir`n`nInstall Console.bat را بزنید."
        return 1
    }

    $verText = '?'
    $verFile = Join-Path $installDir 'VERSION.txt'
    if (Test-Path -LiteralPath $verFile) {
        $verText = (Get-Content -LiteralPath $verFile -Raw).Trim()
    }
    Show-InfoBox `
        -En "Install complete. Version $verText installed to:`n$installDir" `
        -Fa "نصب انجام شد. نسخه $verText در:`n$installDir"

    if (-not (Install-DesktopShortcut $installDir)) {
        Show-ErrorBox `
            -En 'Install finished but desktop shortcut failed.' `
            -Fa 'نصب انجام شد ولی شورتکات دسکتاپ ساخته نشد.'
        Start-PeechaApp $installDir
        return 1
    }

    Start-PeechaApp $installDir
    return 0
}

function Show-DatabaseInfo {
    $text = @"
SQL database setup / راه‌اندازی دیتابیس SQL

EN
1. SQL Express is checked automatically when possible.
2. Copy your MDF file to a local folder.
3. Open PeechaSync - Settings tab - DB name is pre-filled.
4. Use Test SQL Connection if needed.

FA
1. سرویس SQL Express در صورت امکان خودکار بررسی می‌شود.
2. فایل MDF را در یک پوشه محلی کپی کنید.
3. PeechaSync را باز کنید - تب تنظیمات - نام DB از قبل پر است.
4. در صورت نیاز «تست اتصال SQL» را بزنید.

Typical server: .\SQLEXPRESS
Staging: C:\ProgramData\PeechaSync\databases\
"@
    & (Join-Path $lib 'run-bat-hidden.ps1') -BatPath (Join-Path $lib 'ensure-sql-express.bat') -WorkingDir $lib | Out-Null
    $staging = 'C:\ProgramData\PeechaSync\databases'
    if (-not (Test-Path -LiteralPath $staging)) {
        New-Item -ItemType Directory -Path $staging -Force | Out-Null
    }
    $open = [System.Windows.Forms.MessageBox]::Show(
        $text + "`n`nOpen staging folder? / پوشه staging باز شود؟",
        'PeechaSync - SQL',
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Information
    )
    if ($open -eq [System.Windows.Forms.DialogResult]::Yes) {
        Start-Process -FilePath 'explorer.exe' -ArgumentList $staging
    }
}

function Invoke-FullUninstall {
    $installDir = Get-InstallDir
    $installed = Test-Path -LiteralPath (Join-Path $installDir 'Run-PeechaSync.bat')

    $warn = @"
Complete uninstall of the installed PeechaSync version?

Install folder:
$installDir

Removed: program files, Python runtime, shortcuts, update cache
Kept: license, settings, maps, images, .venv (faster reinstall)

Press 1 after this to install fresh from this setup ZIP.

حذف کامل نسخه نصب‌شده PeechaSync؟

پوشه نصب:
$installDir

حذف می‌شود: فایل‌های برنامه، پایتون، شورتکات، کش بروزرسانی
نگه داشته می‌شود: لایسنس، تنظیمات، نقشه‌ها، .venv

بعد از حذف، دکمه ۱ را بزنید تا نصب تازه انجام شود.
"@
    if (-not $installed) {
        $warn = @"
No PeechaSync installation found in:
$installDir

Cleanup will remove shortcuts and pending update files only.

نسخه نصب‌شده در این مسیر پیدا نشد:
$installDir

فقط شورتکات و فایل‌های بروزرسانی معلق پاک می‌شوند.
"@
    }

    $ask = [System.Windows.Forms.MessageBox]::Show(
        $warn + "`n`nClose PeechaSync completely before continuing.`n`nقبل از ادامه PeechaSync را کامل ببندید.",
        'PeechaSync - Full uninstall / حذف کامل',
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Warning
    )
    if ($ask -ne [System.Windows.Forms.DialogResult]::Yes) { return }

    & (Join-Path $lib 'kill-peecha-processes.bat') | Out-Null

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'PeechaSync'
    $form.Size = New-Object System.Drawing.Size(480, 180)
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.BackColor = $Theme.Soft
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
    $form.TopMost = $true

    $label = New-Object System.Windows.Forms.Label
    $label.AutoSize = $false
    $label.Size = New-Object System.Drawing.Size(440, 48)
    $label.Location = New-Object System.Drawing.Point(20, 24)
    $label.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $label.ForeColor = $Theme.Text
    $label.Text = "Removing installed version...`nدر حال حذف نسخه نصب‌شده..."
    $form.Controls.Add($label)

    $bar = New-Object System.Windows.Forms.ProgressBar
    $bar.Style = 'Marquee'
    $bar.MarqueeAnimationSpeed = 30
    $bar.Size = New-Object System.Drawing.Size(440, 18)
    $bar.Location = New-Object System.Drawing.Point(20, 88)
    $form.Controls.Add($bar)

    $form.Add_Shown({ $form.Activate() })
    $form.Show()
    [System.Windows.Forms.Application]::DoEvents()

    $bat = Join-Path $lib 'uninstall-app.bat'
    $rc = & (Join-Path $lib 'run-bat-hidden.ps1') -BatPath $bat -WorkingDir $lib

    $form.Close()
    $form.Dispose()

    if ($rc -ne 0) {
        $logPath = Join-Path $env:LOCALAPPDATA 'PeechaSync\uninstall-last.log'
        $tail = ''
        if (Test-Path -LiteralPath $logPath) {
            $tail = (Get-Content -LiteralPath $logPath -Tail 6 -ErrorAction SilentlyContinue) -join "`n"
        }
        Show-ErrorBox `
            -En "Uninstall failed. Close PeechaSync from the taskbar and try again.`n`n$tail" `
            -Fa "حذف انجام نشد. PeechaSync را از نوار وظیفه ببندید و دوباره امتحان کنید.`n`n$tail"
        return
    }
    $installDir = Get-InstallDir
    $markerPs = Join-Path $lib 'install-markers.ps1'
    $programLeft = $false
    if (Test-Path -LiteralPath $markerPs) {
        . $markerPs
        $programLeft = Test-PeechaProgramInstalled $installDir
    } else {
        $programLeft = (Test-Path -LiteralPath (Join-Path $installDir 'main.pyc')) -or
            (Test-Path -LiteralPath (Join-Path $installDir 'python\python.exe'))
    }
    if ($programLeft) {
        Show-ErrorBox `
            -En 'Some program files remain. Close PeechaSync and press 3 again, or run as Administrator.' `
            -Fa 'هنوز فایل برنامه مانده. PeechaSync را ببندید و دوباره دکمه ۳ را بزنید.'
        return
    }
    Show-InfoBox `
        -En 'Uninstall complete. Press 1 to install the new version.' `
        -Fa 'حذف کامل انجام شد. برای نصب نسخه جدید دکمه ۱ را بزنید.'
}

function Invoke-Uninstall {
    Invoke-FullUninstall
}

function Start-InstallFromMenu {
    param($Form)
    $Form.Tag = 'install'
    $Form.Close()
}

function Start-CheckFromMenu {
    param($Form)
    $Form.Tag = 'check'
    $Form.Close()
}

function Invoke-Check {
    $checkBat = Join-Path $packageRoot '_tools\Check-PeechaSync.bat'
    if (-not (Test-Path -LiteralPath $checkBat)) {
        Show-ErrorBox `
            -En 'Diagnostic tool not found. Re-extract the full ZIP (folder _tools).' `
            -Fa 'فایل بررسی پیدا نشد. ZIP را کامل Extract کنید (پوشه _tools).'
        return 1
    }
    $checkDir = Split-Path -Parent $checkBat
    Start-Process -FilePath $env:ComSpec `
        -ArgumentList '/c', "`"$checkBat`"" `
        -WorkingDirectory $checkDir `
        -Wait | Out-Null
    return 0
}

function Show-Launcher {
    while ($true) {
        $ver = Get-AppVersion

        $form = New-Object System.Windows.Forms.Form
        $form.Text = 'PeechaSync Setup'
        $form.Size = New-Object System.Drawing.Size(480, 460)
        $form.StartPosition = 'CenterScreen'
        $form.FormBorderStyle = 'FixedDialog'
        $form.MaximizeBox = $false
        $form.MinimizeBox = $false
        $form.BackColor = $Theme.Soft
        $form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
        $form.KeyPreview = $true

        $header = New-Object System.Windows.Forms.Panel
        $header.Size = New-Object System.Drawing.Size(464, 76)
        $header.Location = New-Object System.Drawing.Point(0, 0)
        $header.BackColor = $Theme.Primary
        $form.Controls.Add($header)

        $title = New-Object System.Windows.Forms.Label
        $title.AutoSize = $false
        $title.Size = New-Object System.Drawing.Size(464, 34)
        $title.Location = New-Object System.Drawing.Point(0, 14)
        $title.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
        $title.Font = New-Object System.Drawing.Font('Segoe UI', 14, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = $Theme.White
        $title.Text = 'PeechaSync Setup'
        $header.Controls.Add($title)

        $verLbl = New-Object System.Windows.Forms.Label
        $verLbl.AutoSize = $false
        $verLbl.Size = New-Object System.Drawing.Size(464, 24)
        $verLbl.Location = New-Object System.Drawing.Point(0, 48)
        $verLbl.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
        $verLbl.ForeColor = [System.Drawing.Color]::FromArgb(203, 213, 225)
        $verLbl.Text = "Version $ver / نسخه $ver"
        $header.Controls.Add($verLbl)

        $hint = New-Object System.Windows.Forms.Label
        $hint.AutoSize = $false
        $hint.Size = New-Object System.Drawing.Size(420, 44)
        $hint.Location = New-Object System.Drawing.Point(30, 88)
        $hint.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
        $hint.ForeColor = $Theme.SubText
        $hint.Text = "Press 1 to install, 3 to remove old version`nدکمه ۱ = نصب   دکمه ۳ = حذف کامل نسخه قبلی"
        $form.Controls.Add($hint)

        $installBtn = New-Object System.Windows.Forms.Button
        $installBtn.Location = New-Object System.Drawing.Point(36, 142)
        $installBtn.Text = "1   Install and run`r`n     نصب و اجرا"
        $installBtn.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
        Set-PrimaryButtonStyle $installBtn
        Set-ActionButtonSize $installBtn 62
        $installBtn.Add_Click({ Start-InstallFromMenu $form })
        $form.Controls.Add($installBtn)

        $checkBtn = New-Object System.Windows.Forms.Button
        $checkBtn.Location = New-Object System.Drawing.Point(36, 214)
        $checkBtn.Text = "2   Diagnostic check`r`n     بررسی خطا و گزارش"
        $checkBtn.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
        Set-SecondaryButtonStyle $checkBtn
        Set-ActionButtonSize $checkBtn 62
        $checkBtn.Add_Click({ Start-CheckFromMenu $form })
        $form.Controls.Add($checkBtn)

        $uninstallBtn = New-Object System.Windows.Forms.Button
        $uninstallBtn.Location = New-Object System.Drawing.Point(36, 286)
        $uninstallBtn.Text = "3   Full uninstall (old version)`r`n     حذف کامل نسخه نصب‌شده"
        $uninstallBtn.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
        Set-SecondaryButtonStyle $uninstallBtn
        Set-ActionButtonSize $uninstallBtn 62
        $uninstallBtn.Add_Click({ Invoke-FullUninstall })
        $form.Controls.Add($uninstallBtn)

        $exitBtn = New-Object System.Windows.Forms.LinkLabel
        $exitBtn.AutoSize = $true
        $exitBtn.Location = New-Object System.Drawing.Point(350, 372)
        $exitBtn.LinkColor = $Theme.SubText
        $exitBtn.Text = "0   Exit / خروج"
        $exitBtn.Add_LinkClicked({ $form.Tag = 'exit'; $form.Close() })
        $form.Controls.Add($exitBtn)

        $form.AcceptButton = $installBtn

        $form.Add_KeyDown({
            param($sender, $e)
            if ($e.KeyCode -eq [System.Windows.Forms.Keys]::D1 -or $e.KeyCode -eq [System.Windows.Forms.Keys]::NumPad1) {
                Start-InstallFromMenu $form
                $e.Handled = $true
            }
            if ($e.KeyCode -eq [System.Windows.Forms.Keys]::D2 -or $e.KeyCode -eq [System.Windows.Forms.Keys]::NumPad2) {
                Start-CheckFromMenu $form
                $e.Handled = $true
            }
            if ($e.KeyCode -eq [System.Windows.Forms.Keys]::D3 -or $e.KeyCode -eq [System.Windows.Forms.Keys]::NumPad3) {
                Invoke-FullUninstall
                $e.Handled = $true
            }
            if ($e.KeyCode -eq [System.Windows.Forms.Keys]::D0 -or $e.KeyCode -eq [System.Windows.Forms.Keys]::NumPad0) {
                $form.Tag = 'exit'
                $form.Close()
                $e.Handled = $true
            }
        })

        $form.Add_Shown({
            $form.Activate()
            $installBtn.Focus()
        })

        [void]$form.ShowDialog()
        $tag = $form.Tag
        $form.Dispose()

        if (-not $tag -or $tag -eq 'exit') { return }
        if ($tag -eq 'install') {
            if ((Invoke-Install) -eq 0) { return }
            continue
        }
        if ($tag -eq 'check') {
            Invoke-Check | Out-Null
            continue
        }
    }
}

function Show-Menu {
    while ($true) {
        $ver = Get-AppVersion

        $form = New-Object System.Windows.Forms.Form
        $form.Text = 'PeechaSync Setup'
        $form.Size = New-Object System.Drawing.Size(480, 520)
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.BackColor = $Theme.Soft
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
    $form.KeyPreview = $true

    $header = New-Object System.Windows.Forms.Panel
    $header.Size = New-Object System.Drawing.Size(424, 72)
    $header.Location = New-Object System.Drawing.Point(0, 0)
    $header.BackColor = $Theme.Primary
    $form.Controls.Add($header)

    $title = New-Object System.Windows.Forms.Label
    $title.AutoSize = $false
    $title.Size = New-Object System.Drawing.Size(424, 32)
    $title.Location = New-Object System.Drawing.Point(0, 12)
    $title.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $title.Font = New-Object System.Drawing.Font('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
    $title.ForeColor = $Theme.White
    $title.Text = 'PeechaSync Setup'
    $header.Controls.Add($title)

    $verLbl = New-Object System.Windows.Forms.Label
    $verLbl.AutoSize = $false
    $verLbl.Size = New-Object System.Drawing.Size(424, 22)
    $verLbl.Location = New-Object System.Drawing.Point(0, 44)
    $verLbl.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $verLbl.ForeColor = [System.Drawing.Color]::FromArgb(203, 213, 225)
    $verLbl.Text = "Version $ver / نسخه $ver"
    $header.Controls.Add($verLbl)

    $hint = New-Object System.Windows.Forms.Label
    $hint.AutoSize = $false
    $hint.Size = New-Object System.Drawing.Size(400, 36)
    $hint.Location = New-Object System.Drawing.Point(20, 84)
    $hint.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $hint.ForeColor = $Theme.SubText
    $hint.Text = "Press 1 or click the button below`nدکمه ۱ = نصب آفلاین"
    $form.Controls.Add($hint)

    $installBtn = New-Object System.Windows.Forms.Button
    $installBtn.Location = New-Object System.Drawing.Point(36, 128)
    $installBtn.Text = "1   Install and run`r`n     نصب و اجرا"
    $installBtn.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
    Set-PrimaryButtonStyle $installBtn
    Set-ActionButtonSize $installBtn 62
    $installBtn.Add_Click({ Start-InstallFromMenu $form })
    $form.Controls.Add($installBtn)

    $btn2 = New-Object System.Windows.Forms.Button
    $btn2.Location = New-Object System.Drawing.Point(36, 200)
    $btn2.Text = "2   Diagnostic check`r`n     بررسی خطا و گزارش"
    $btn2.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
    Set-SecondaryButtonStyle $btn2
    Set-ActionButtonSize $btn2 62
    $btn2.Add_Click({ Start-CheckFromMenu $form })
    $form.Controls.Add($btn2)

    $btn3 = New-Object System.Windows.Forms.Button
    $btn3.Size = New-Object System.Drawing.Size(388, 44)
    $btn3.Location = New-Object System.Drawing.Point(36, 272)
    $btn3.Text = "3  SQL database / دیتابیس"
    $btn3.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
    Set-SecondaryButtonStyle $btn3
    $btn3.Add_Click({ Show-DatabaseInfo })
    $form.Controls.Add($btn3)

    $btn4 = New-Object System.Windows.Forms.Button
    $btn4.Size = New-Object System.Drawing.Size(388, 44)
    $btn4.Location = New-Object System.Drawing.Point(36, 326)
    $btn4.Text = "4  Full uninstall / حذف کامل نسخه نصب‌شده"
    $btn4.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
    Set-SecondaryButtonStyle $btn4
    $btn4.Add_Click({ Invoke-Uninstall })
    $form.Controls.Add($btn4)

    $detailsBtn = New-Object System.Windows.Forms.LinkLabel
    $detailsBtn.AutoSize = $true
    $detailsBtn.Location = New-Object System.Drawing.Point(36, 388)
    $detailsBtn.LinkColor = $Theme.Primary
    $detailsBtn.ActiveLinkColor = $Theme.Hover
    $detailsBtn.Text = "Details / جزئیات"
    $detailsBtn.Add_LinkClicked({ Show-SetupDetails })
    $form.Controls.Add($detailsBtn)

    $exitBtn = New-Object System.Windows.Forms.LinkLabel
    $exitBtn.AutoSize = $true
    $exitBtn.Location = New-Object System.Drawing.Point(350, 388)
    $exitBtn.LinkColor = $Theme.SubText
    $exitBtn.Text = "0  Exit / خروج"
    $exitBtn.Add_LinkClicked({ $form.Tag = 'exit'; $form.Close() })
    $form.Controls.Add($exitBtn)

    $form.AcceptButton = $installBtn

    $form.Add_KeyDown({
        param($sender, $e)
        if ($e.KeyCode -eq [System.Windows.Forms.Keys]::D1 -or $e.KeyCode -eq [System.Windows.Forms.Keys]::NumPad1) {
            Start-InstallFromMenu $form
            $e.Handled = $true
        }
        if ($e.KeyCode -eq [System.Windows.Forms.Keys]::D2 -or $e.KeyCode -eq [System.Windows.Forms.Keys]::NumPad2) {
            Start-CheckFromMenu $form
            $e.Handled = $true
        }
        if ($e.KeyCode -eq [System.Windows.Forms.Keys]::D4 -or $e.KeyCode -eq [System.Windows.Forms.Keys]::NumPad4) {
            Invoke-FullUninstall
            $e.Handled = $true
        }
        if ($e.KeyCode -eq [System.Windows.Forms.Keys]::D0 -or $e.KeyCode -eq [System.Windows.Forms.Keys]::NumPad0) {
            $form.Tag = 'exit'
            $form.Close()
            $e.Handled = $true
        }
    })

    $form.Add_Shown({
        $form.Activate()
        $installBtn.Focus()
    })

    [void]$form.ShowDialog()
    $tag = $form.Tag
    $form.Dispose()

    if (-not $tag -or $tag -eq 'exit') { return }
    if ($tag -eq 'install') {
        if ((Invoke-Install) -eq 0) { return }
        continue
    }
    if ($tag -eq 'check') {
        Invoke-Check | Out-Null
        continue
    }
}
}

if ($Mode -eq 'install') {
    exit (Invoke-Install)
} elseif ($Mode -eq 'menu') {
    Show-Menu
} else {
    Show-Launcher
}
