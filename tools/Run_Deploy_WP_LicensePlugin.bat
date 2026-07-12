@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"
REM Auto-deploy Peecha License Manager via FTP (no manual copy)
REM بروزرسانی افزونه از طریق FTP - بدون کپی دستی

if not exist "%~dp0Deploy-WP-LicensePlugin.ps1" (
  echo Script not found in: %~dp0
  pause
  exit /b 1
)

if not exist "%~dp0wp-license-deploy.local.json" (
  echo Config missing. Run Setup_WP_LicenseDeploy.bat first.
  echo فایل تنظیم نیست. اول Setup_WP_LicenseDeploy.bat را بزنید.
  echo.
  pause
  exit /b 1
)

set "MODE=update"
if /I "%~1"=="install" set "MODE=install"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Deploy-WP-LicensePlugin.ps1" -Mode %MODE%
if errorlevel 1 (
  echo.
  echo Deploy failed. Check FTP user/password in wp-license-deploy.local.json
  echo.
  pause
  exit /b 1
)

echo.
if /I "%MODE%"=="update" (
  echo Done. Refresh wp-admin to confirm the new version.
  echo تمام. صفحه ادمین را رفرش کنید تا نسخه جدید را ببینید.
) else (
  echo Open the web-install URL shown above, then delete web-install.php.
  echo لینک web-install را باز کنید، بعد web-install.php را از سرور حذف کنید.
)
pause
