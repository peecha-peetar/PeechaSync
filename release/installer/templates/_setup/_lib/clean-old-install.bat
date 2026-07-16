@echo off
setlocal EnableExtensions
call "%~dp0paths.bat"

set "TARGET=%DEFAULT_INSTALL%"
call "%~dp0resolve-install-dir.bat" TARGET "%DEFAULT_INSTALL%"
if not exist "%TARGET%" exit /b 0

echo Cleaning old program files in %TARGET%
echo Keeping license, settings, maps, images, .venv

set "CLEAN_PS=%~dp0..\engine\app\Force-CleanProgramFiles.ps1"
if exist "%CLEAN_PS%" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%CLEAN_PS%" -InstallRoot "%TARGET%"
)

taskkill /F /IM pythonw.exe /T 2>nul
taskkill /F /IM python.exe /T 2>nul
call "%~dp0kill-peecha-processes.bat" 2>nul

for %%D in (sync_app python _packages release) do (
    if exist "%TARGET%\%%D" rd /s /q "%TARGET%\%%D" 2>nul
)

for %%F in (
    main.py main.pyc requirements.txt PeechaSync.ico VERSION.txt
    Run-PeechaSync.bat Launch-PeechaSync.vbs
    launch-gui.cmd launch-gui.ps1 set-python-env.bat test-import.ps1 verify-main-pyc.ps1
    show-startup-error.bat show-user-message.ps1 check-internet.bat
    peecha-version-refresh.ps1 Apply-ClientUpdate.ps1
    peecha-apply-cached-update.ps1 Apply-CachedUpdate.bat
    .peecha-pyc-only .peecha-release .peecha-installed-version
) do (
    if exist "%TARGET%\%%F" del /f /q "%TARGET%\%%F" 2>nul
)

if exist "%TARGET%\__pycache__" rd /s /q "%TARGET%\__pycache__" 2>nul

exit /b 0
