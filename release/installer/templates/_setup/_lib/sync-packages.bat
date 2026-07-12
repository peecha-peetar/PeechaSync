@echo off
setlocal EnableExtensions
set "SRC=%~1"
set "DST=%~2"
set "LOG=%LOCALAPPDATA%\PeechaSync\install-errors.log"
if "%SRC%"=="" exit /b 1
if "%DST%"=="" exit /b 2

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync-packages-copy.ps1" -SourceRoot "%SRC%" -DestRoot "%DST%" -LogPath "%LOG%"
if not errorlevel 1 exit /b 0

echo [%date% %time%] sync-packages: PowerShell copy failed - trying robocopy>> "%LOG%"
if not exist "%SRC%\*.whl" exit /b 0
if not exist "%DST%" mkdir "%DST%" 2>nul
robocopy "%SRC%" "%DST%" *.whl /R:1 /W:1 /NFL /NDL /NJH /NJS /nc /ns /np >nul
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
    echo [%date% %time%] sync-packages: robocopy failed rc=%RC%>> "%LOG%"
    exit /b 1
)
exit /b 0
