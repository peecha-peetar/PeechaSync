@echo off
setlocal EnableExtensions
call "%~dp0paths.bat"

set "LOG=%LOCALAPPDATA%\PeechaSync\uninstall-last.log"
if not exist "%LOCALAPPDATA%\PeechaSync" mkdir "%LOCALAPPDATA%\PeechaSync" 2>nul
echo [%date% %time%] uninstall start > "%LOG%"

call "%~dp0kill-peecha-processes.bat"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0full-uninstall.ps1" -LogPath "%LOG%"
if errorlevel 1 (
    echo uninstall failed>>"%LOG%"
    exit /b 1
)

echo uninstall ok>>"%LOG%"
exit /b 0
