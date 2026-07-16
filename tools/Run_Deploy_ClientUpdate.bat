@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Deploy PeechaSync client update mirror to peecha.ir
echo استقرار آینه بروزرسانی کلاینت روی peecha.ir
echo.
echo VPN must be OFF for FTP (Iran hosting).
echo VPN باید خاموش باشد.
echo.
if /I "%~1"=="upload-only" (
    echo Upload only - skip ZIP rebuild / فقط آپلود بدون build دوباره
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Deploy-ClientUpdateMirror.ps1" -SkipBuild
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Deploy-ClientUpdateMirror.ps1"
)
if errorlevel 1 (
    echo.
    echo If login failed 531: run tools\Setup_WP_LicenseDeploy.bat and set correct FTP password.
    echo Then test: tools\Test-WP-LicenseFtp.bat
    echo Retry upload: tools\Run_Deploy_ClientUpdate.bat upload-only
    pause
)
