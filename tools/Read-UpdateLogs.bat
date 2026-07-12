@echo off
chcp 65001 >nul
set "STATE=%LOCALAPPDATA%\PeechaSync"
set "CACHE=%TEMP%\PeechaSync-updates"
echo === PeechaSync update diagnostics ===
echo.
echo [1] update-last.log
echo     %STATE%\update-last.log
if exist "%STATE%\update-last.log" (
    echo --- last 40 lines ---
    powershell -NoProfile -Command "Get-Content -LiteralPath '%STATE%\update-last.log' -Tail 40 -Encoding UTF8"
) else (
    echo     (not found - old client versions may not write this file)
)
echo.
echo [2] startup-errors.log
echo     %STATE%\startup-errors.log
if exist "%STATE%\startup-errors.log" (
    echo --- last 25 lines ---
    powershell -NoProfile -Command "Get-Content -LiteralPath '%STATE%\startup-errors.log' -Tail 25 -Encoding UTF8"
) else (
    echo     (not found)
)
echo.
echo [3] pending-update.json
echo     %STATE%\pending-update.json
if exist "%STATE%\pending-update.json" type "%STATE%\pending-update.json"
echo.
echo [4] cached ZIP downloads
echo     %CACHE%
if exist "%CACHE%" dir /o-d "%CACHE%\PeechaSync-*.zip" 2>nul
echo.
echo [5] install.loc
if exist "%STATE%\install.loc" (
    echo     %STATE%\install.loc
    type "%STATE%\install.loc"
)
echo.
pause
