param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('internet-packages', 'venv', 'main', 'folder', 'launch')]
    [string]$Code
)

Add-Type -AssemblyName System.Windows.Forms

$log = Join-Path $env:LOCALAPPDATA 'PeechaSync\startup-errors.log'
$msgs = @{
    'internet-packages' = @"
Required packages are not installed.

Run Install PeechaSync.bat again from the extracted ZIP folder.

---

پکیج‌های لازم نصب نشده‌اند.

دوباره Install PeechaSync.bat را از همان پوشه Extract‌شده اجرا کنید.
"@
    'venv' = @"
Installation is incomplete.

Run Install PeechaSync.bat again from the extracted ZIP folder.

---

نصب کامل نشده است.

دوباره Install PeechaSync.bat را از همان پوشه Extract‌شده بزنید.
"@
    'main' = @"
Program files are missing.

Run Install PeechaSync.bat again.

---

فایل‌های برنامه نیست.

دوباره Install PeechaSync.bat را اجرا کنید.
"@
    'folder' = @"
Install folder not found.

Run Install PeechaSync.bat again.

---

پوشه نصب پیدا نشد.

دوباره Install PeechaSync.bat را اجرا کنید.
"@
    'launch' = @"
PeechaSync could not start.

Run Install PeechaSync.bat again (option 1).

If it happens again, send us startup-errors.log.

---

برنامه اجرا نشد.

دوباره Install PeechaSync.bat را بزنید (دکمه ۱).

اگر باز هم همین شد، فایل startup-errors.log را بفرستید.
"@
}

$icon = [System.Windows.Forms.MessageBoxIcon]::Warning
if ($Code -eq 'folder') { $icon = [System.Windows.Forms.MessageBoxIcon]::Error }

$text = $msgs[$Code] + "`n`nLog: $log"
[void][System.Windows.Forms.MessageBox]::Show($text, 'PeechaSync', 'OK', $icon)
