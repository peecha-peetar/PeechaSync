@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1

set "ROOT=%~dp0"
if exist "%LOCALAPPDATA%\PeechaSync\install.loc" (
    set /p PECHA_INST=<"%LOCALAPPDATA%\PeechaSync\install.loc"
    if exist "!PECHA_INST!\sync_app" (
        set "ROOT=!PECHA_INST!\"
    )
)

set "LOG=%LOCALAPPDATA%\PeechaSync\update-last.log"
if not exist "%LOCALAPPDATA%\PeechaSync" mkdir "%LOCALAPPDATA%\PeechaSync" 2>nul
echo [%date% %time%] Apply-CachedUpdate start root=%ROOT% >> "%LOG%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-Process pythonw,python -EA 0 | Where-Object { $_.Path -and ($_.Path -like '*PeechaSync*') } | Stop-Process -Force -EA 0"
timeout /t 3 /nobreak >nul

if exist "%ROOT%peecha-apply-cached-update.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%peecha-apply-cached-update.ps1" -InstallRoot "%ROOT%." >>"%LOG%" 2>&1
    if errorlevel 1 goto :fail
    echo [%date% %time%] Apply-CachedUpdate ok >> "%LOG%"
    if /i not "%~1"=="silent" (
        echo Done. Start PeechaSync again.
        echo انجام شد. PeechaSync را دوباره باز کنید.
        pause
    )
    exit /b 0
)

echo Apply script missing: %ROOT%peecha-apply-cached-update.ps1
echo [%date% %time%] peecha-apply-cached-update.ps1 missing >> "%LOG%"
:fail
if /i not "%~1"=="silent" (
    echo Update failed. Send update-last.log from %%LOCALAPPDATA%%\PeechaSync
    echo خطا در نصب. فایل update-last.log را بفرستید.
    pause
)
exit /b 1
