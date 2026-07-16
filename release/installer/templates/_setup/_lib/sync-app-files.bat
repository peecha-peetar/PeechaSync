@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "SRC=%~1"
set "DST=%~2"
set "LOG=%LOCALAPPDATA%\PeechaSync\install-errors.log"

if "%SRC%"=="" exit /b 1
if "%DST%"=="" exit /b 2
if not exist "%SRC%" (
    echo [%date% %time%] sync-app: source missing %SRC%>> "%LOG%"
    exit /b 3
)
if not exist "%DST%" mkdir "%DST%" 2>nul

if not exist "%SRC%\sync_app" (
    echo [%date% %time%] sync-app: sync_app missing in %SRC%>> "%LOG%"
    exit /b 4
)

echo [%date% %time%] sync-app: src=%SRC% dst=%DST%>> "%LOG%"

call "%~dp0kill-peecha-processes.bat"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync-app-copy.ps1" -SourceRoot "%SRC%" -DestRoot "%DST%" -LogPath "%LOG%"
if not errorlevel 1 exit /b 0

echo [%date% %time%] sync-app: PowerShell copy failed - trying robocopy>> "%LOG%"

if exist "%DST%\sync_app" (
    set "BAK=%DST%\_sync_app_remove_%RANDOM%"
    move /Y "%DST%\sync_app" "!BAK!" >nul 2>&1
    if exist "!BAK!" rd /s /q "!BAK!" 2>nul
    if exist "%DST%\sync_app" rd /s /q "%DST%\sync_app" 2>nul
    ping 127.0.0.1 -n 2 >nul
)
if not exist "%DST%\sync_app" mkdir "%DST%\sync_app" 2>nul

robocopy "%SRC%\sync_app" "%DST%\sync_app" /E /R:5 /W:3 /NFL /NDL /NJH /NJS /nc /ns /np >nul
set "RC=!ERRORLEVEL!"
if !RC! GEQ 8 (
    echo [%date% %time%] sync-app: robocopy failed rc=!RC!>> "%LOG%"
    exit /b 1
)

for %%F in (main.pyc main.py requirements.txt PeechaSync.ico VERSION.txt Run-PeechaSync.bat Launch-PeechaSync.vbs launch-gui.cmd launch-gui.ps1 patch-launch-env.cmd repair-launch-env.cmd set-python-env.bat test-import.ps1 test-bootstrap.ps1 verify-main-pyc.ps1 show-startup-error.bat show-user-message.ps1 check-internet.bat peecha-version-refresh.ps1 Apply-ClientUpdate.ps1 Force-CleanProgramFiles.ps1 Assert-InstalledVersion.ps1 peecha-apply-cached-update.ps1 Apply-CachedUpdate.bat .peecha-pyc-only .peecha-release) do (
    if exist "%SRC%\%%F" copy /y "%SRC%\%%F" "%DST%\%%F" >nul 2>&1
)

exit /b 0
