@echo off
chcp 65001 >nul
cd /d "%~dp0.."
REM Deploy Peecha License Manager — wp-admin upload (no cPanel)
REM نصب افزونه از wp-admin بدون cPanel
set "ACTION=install"
if /I "%~1"=="remove" set "ACTION=remove"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-WP-LicensePlugin.ps1" -Action %ACTION%
echo.
echo Upload update.zip in wp-admin -^> Peecha Licenses -^> Update plugin
echo یا update.zip را در لایسنس‌های پیچا - بروزرسانی افزونه آپلود کنید.
pause
