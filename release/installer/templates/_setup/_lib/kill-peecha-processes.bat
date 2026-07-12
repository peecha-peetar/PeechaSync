@echo off
setlocal EnableExtensions
set "INSTALL_DIR="
if exist "%LOCALAPPDATA%\PeechaSync\install.loc" (
    for /f "usebackq delims=" %%D in ("%LOCALAPPDATA%\PeechaSync\install.loc") do set "INSTALL_DIR=%%D"
)
if defined INSTALL_DIR (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill-peecha-processes.ps1" -InstallDirs "%INSTALL_DIR%" -WaitSeconds 3
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill-peecha-processes.ps1" -WaitSeconds 3
)
exit /b 0
