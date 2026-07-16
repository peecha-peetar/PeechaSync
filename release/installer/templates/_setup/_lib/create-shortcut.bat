@echo off
call "%~dp0paths.bat"
if "%INSTALL_DIR%"=="" exit /b 1

set "TARGET_BAT=%INSTALL_DIR%\Run-PeechaSync.bat"
if not exist "%TARGET_BAT%" exit /b 1

call "%~dp0resolve-desktop.bat"

set "ICON_FILE=%INSTALL_DIR%\PeechaSync.ico"
if not exist "%ICON_FILE%" set "ICON_FILE=%PKG_ICON%"
if not exist "%ICON_FILE%" set "ICON_FILE="

set "SC_SHORTCUT=%SHORTCUT%"
set "SC_TARGET_BAT=%TARGET_BAT%"
set "SC_WORKING_DIR=%INSTALL_DIR%"
set "SC_ICON_FILE=%ICON_FILE%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create-shortcut.ps1"
if errorlevel 1 (
    echo Shortcut create failed. Use %TARGET_BAT% to run.
    exit /b 1
)
exit /b 0
