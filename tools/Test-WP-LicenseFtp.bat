@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Test FTP login to peecha.ir (no upload)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Test-WP-LicenseFtp.ps1"
if errorlevel 1 pause
