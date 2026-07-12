@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Build PeechaSync client ZIP only
echo ساخت ZIP کلاینت
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Deploy-ClientUpdateMirror.ps1" -BuildOnly
if errorlevel 1 pause
