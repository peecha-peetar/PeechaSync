param(
    [string]$Title = 'PeechaSync',
    [string]$Text = '',
    [ValidateSet('', 'install-packages-missing')]
    [string]$Code = '',
    [ValidateSet('OK', 'OKCancel', 'YesNo')]
    [string]$Buttons = 'OK',
    [ValidateSet('Error', 'Warning', 'Information', 'Question')]
    [string]$Icon = 'Information'
)

Add-Type -AssemblyName System.Windows.Forms

if ($Code -eq 'install-packages-missing') {
    $Text = @"
Installer packages are missing.
Extract the full ZIP again (folder _setup\engine\packages).

---

پکیج‌های نصاب نیست.
ZIP را کامل Extract کنید (پوشه _setup\engine\packages).
"@
    $Icon = 'Warning'
}

if (-not $Text) {
    Write-Error 'Text or Code is required.'
    exit 1
}

$btn = [System.Windows.Forms.MessageBoxButtons]::$Buttons
$ico = [System.Windows.Forms.MessageBoxIcon]::$Icon
$result = [System.Windows.Forms.MessageBox]::Show($Text, $Title, $btn, $ico)
if ($Buttons -eq 'YesNo' -and $result -eq [System.Windows.Forms.DialogResult]::Yes) { exit 0 }
if ($Buttons -eq 'YesNo') { exit 1 }
exit 0
