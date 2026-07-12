@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Finish delivery: deploy plugin 1.0.31+ then client mirror (VPN OFF for FTP)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Deploy-WP-LicensePlugin.ps1" -AlsoDeployClient
if errorlevel 1 pause
