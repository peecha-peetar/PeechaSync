@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo Step 1: force git sync
call "%~dp0Force-Git-Sync.bat"
if errorlevel 1 exit /b 1

echo.
echo Step 2: deploy plugin (VPN OFF recommended)
call "%~dp0tools\Run_Deploy_WP_LicensePlugin.bat"
exit /b %ERRORLEVEL%
