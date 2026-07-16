@echo off
chcp 65001 >nul
cd /d "%~dp0"
title PeechaSync Install
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_setup\_lib\install-with-console.ps1"
set "RC=%ERRORLEVEL%"
echo.
echo Press any key to close...
pause >nul
exit /b %RC%
