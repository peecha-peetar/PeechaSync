# این اسکریپت برایِ هر پروفایلِ موجودِ PeechaSync (هر پروفایل = یک فروشگاه/
# دیتابیسِ جدا)، یک «تسکِ زمان‌بندی‌شده»‌یِ ویندوز جداگانه می‌سازه که همگام‌سازیِ
# خودکارِ همون پروفایل رو بدونِ نیاز به بازکردنِ برنامه (یا لاگین‌بودن با اون
# پروفایلِ خاص) اجرا می‌کنه — یعنی می‌شه هم‌زمان چند فروشگاه رو خودکار
# همگام‌سازی کرد.
#
# طرزِ استفاده: این فایل رو تویِ پوشه‌یِ نصبِ PeechaSync (همون‌جایی که
# main.py هست) با «Run with PowerShell» یا از خطِ فرمان اجرا کنید:
#     powershell -ExecutionPolicy Bypass -File setup-auto-sync-tasks.ps1
#
# قبل از اجرا: برایِ هر پروفایل، از خودِ برنامه وارد بشید، تبِ «همگام‌سازیِ
# خودکار» رو باز کنید، ماژول‌هایِ موردِنظر رو تیک بزنید، فاصله‌یِ زمانی رو
# انتخاب کنید، و «فعال‌سازیِ حالتِ اتوماتیک» رو روشن کنید. این اسکریپت فقط
# باعث می‌شه همون تنظیماتِ ذخیره‌شده حتی بدونِ بازبودنِ برنامه هم اجرا بشه.
#
# نکته: این اسکریپت هر IntervalMinutes دقیقه (پیش‌فرض ۱۵) تسک رو صدا می‌زنه؛
# خودِ PeechaSync تشخیص می‌ده که طبقِ فاصله‌یِ زمانیِ انتخابیِ شما (که ممکنه
# بیشتر از ۱۵ دقیقه باشه) واقعاً موعدِ اجرا رسیده یا نه — پس صدا زدنِ مکرر
# مشکلی ایجاد نمی‌کنه.

param(
    [int]$IntervalMinutes = 15
)

$ErrorActionPreference = 'Stop'
$WorkDir = (Get-Location).Path.TrimEnd('\')

function Get-MainPath {
    $pycOnly = Join-Path $WorkDir '.peecha-pyc-only'
    $pyc = Join-Path $WorkDir 'main.pyc'
    $py = Join-Path $WorkDir 'main.py'
    if ((Test-Path -LiteralPath $pycOnly) -and (Test-Path -LiteralPath $pyc)) {
        return (Resolve-Path -LiteralPath $pyc).Path
    }
    if (Test-Path -LiteralPath $py) { return (Resolve-Path -LiteralPath $py).Path }
    if (Test-Path -LiteralPath $pyc) { return (Resolve-Path -LiteralPath $pyc).Path }
    return ''
}

function Get-PythonExe {
    # pythonw.exe رو ترجیح می‌ده (بدونِ پنجره‌یِ کنسول) — اگه نبود، python.exe
    foreach ($rel in @('python\pythonw.exe', 'python\python.exe', '.venv\Scripts\pythonw.exe', '.venv\Scripts\python.exe')) {
        $path = Join-Path $WorkDir $rel
        if (Test-Path -LiteralPath $path) {
            return (Resolve-Path -LiteralPath $path).Path
        }
    }
    return ''
}

$mainPath = Get-MainPath
if (-not $mainPath) {
    Write-Host 'خطا: main.py/main.pyc تویِ این پوشه پیدا نشد — این اسکریپت رو تویِ پوشه‌یِ نصبِ PeechaSync اجرا کنید.' -ForegroundColor Red
    exit 2
}

$pythonExe = Get-PythonExe
if (-not $pythonExe) {
    Write-Host 'خطا: پایتونِ داخلیِ PeechaSync پیدا نشد.' -ForegroundColor Red
    exit 3
}

$profilesRoot = Join-Path $env:LOCALAPPDATA 'PeechaSync\profiles'
if (-not (Test-Path -LiteralPath $profilesRoot)) {
    Write-Host 'هیچ پروفایلی پیدا نشد — ابتدا حداقل یک‌بار وارد برنامه بشید و پروفایل(ها) رو بسازید.' -ForegroundColor Yellow
    exit 1
}

$profiles = Get-ChildItem -LiteralPath $profilesRoot -Directory | Select-Object -ExpandProperty Name
if (-not $profiles) {
    Write-Host 'هیچ پروفایلی تویِ profiles\ پیدا نشد.' -ForegroundColor Yellow
    exit 1
}

Write-Host "پایتون: $pythonExe"
Write-Host "main:   $mainPath"
Write-Host ''

foreach ($p in $profiles) {
    $taskName = "PeechaSync-AutoSync-$p"
    $trValue = '"{0}" "{1}" --profile {2}' -f $pythonExe, $mainPath, $p

    schtasks.exe /Create /F /SC MINUTE /MO $IntervalMinutes /TN $taskName /TR $trValue /RL LIMITED | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✔ تسکِ همگام‌سازیِ خودکار برایِ پروفایلِ «$p» ساخته/به‌روزرسانی شد: $taskName" -ForegroundColor Green
    } else {
        Write-Host "✘ ساختِ تسک برایِ پروفایلِ «$p» ناموفق بود (کدِ خطا: $LASTEXITCODE)." -ForegroundColor Red
    }
}

Write-Host ''
Write-Host 'برایِ دیدن/مدیریتِ تسک‌ها: Task Scheduler را باز کنید و پوشه‌یِ ریشه (Task Scheduler Library) را ببینید.'
Write-Host 'برایِ حذفِ یک تسک: schtasks /Delete /TN "PeechaSync-AutoSync-<نامِ پروفایل>" /F'
