@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Publish: build + GitHub + peecha.ir mirror (full pipeline)
echo VPN pauses: ON before git, OFF before FTP
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Publish-Release.ps1" %*
if errorlevel 1 pause
