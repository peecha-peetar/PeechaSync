@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Full repair (force clean + reinstall all program files)
echo تعمیر کامل — همه فایل برنامه عوض می‌شود، تنظیمات حفظ می‌شود
echo.
echo Close PeechaSync completely first...
pause
set "LIB=tools\client-release-deploy\DELIVERY-PeechaSync-1.1.2\PeechaSync-Setup-1.1.2-Portable\PeechaSync-Setup-1.1.2-Portable\_setup\_lib"
if not exist "%LIB%\install-app.bat" ( echo Setup missing & pause & exit /b 1 )
cd /d "%LIB%"
call install-app.bat
echo exit=%ERRORLEVEL%
pause
