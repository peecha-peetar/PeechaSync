@echo off
setlocal EnableExtensions
set "SRC=%~1"
set "DST=%~2"
set "LOG=%LOCALAPPDATA%\PeechaSync\install-errors.log"
if "%SRC%"=="" exit /b 1
if "%DST%"=="" exit /b 2
if not exist "%SRC%\python.exe" (
    echo [%date% %time%] sync-python: source missing %SRC%\python.exe>> "%LOG%"
    exit /b 3
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync-python-copy.ps1" -SourceRoot "%SRC%" -DestRoot "%DST%" -LogPath "%LOG%"
if not errorlevel 1 exit /b 0

echo [%date% %time%] sync-python: PowerShell copy failed - trying robocopy>> "%LOG%"
if exist "%DST%" rd /s /q "%DST%" 2>nul
robocopy "%SRC%" "%DST%" /E /R:2 /W:2 /NFL /NDL /NJH /NJS /nc /ns /np >nul
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
    echo [%date% %time%] sync-python: robocopy failed rc=%RC%>> "%LOG%"
    exit /b 1
)
if not exist "%DST%\python.exe" (
    echo [%date% %time%] sync-python: python.exe missing after copy>> "%LOG%"
    exit /b 1
)
exit /b 0
