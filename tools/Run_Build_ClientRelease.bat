@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
echo Build PeechaSync portable setup ZIP
echo ساخت ZIP نصب Portable
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\release\build_setup_package.ps1"
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)
echo.
echo Output: tools\client-release-deploy\PeechaSync-Setup-*-Portable.zip
pause
