@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Build update.zip for manual / web-update upload
echo ساخت update.zip برای آپلود دستی
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Make-UpdateZip.ps1"
if errorlevel 1 pause
if not errorlevel 1 (
  echo.
  echo Files are in tools\wp-license-deploy\
  explorer "%~dp0wp-license-deploy"
  pause
)
