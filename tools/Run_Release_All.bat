@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title PeechaSync Release v1.x

if not exist "%~dp0wp-license-deploy.local.json" (
    echo.
    echo First time: run Setup_WP_LicenseDeploy.bat and save FTP user/password.
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo  PeechaSync - full release (one command)
echo  OTA + portable setup + git + GitHub + FTP mirror
echo ============================================================
echo.
echo 1. Bump version in sync_app\core\app_version.py (_BUILTIN_VERSION)
echo 2. Script will PAUSE twice for VPN ON / OFF
echo.
echo Output: tools\client-release-deploy\DELIVERY-PeechaSync-VERSION\
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Publish-Release.ps1"
if errorlevel 1 pause
