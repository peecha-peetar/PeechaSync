@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
call "%~dp0paths.bat"

set "INSTALL_DIR=%DEFAULT_INSTALL%"
if exist "%LOC_FILE%" (
    for /f "usebackq delims=" %%D in ("%LOC_FILE%") do set "INSTALL_DIR=%%D"
)

set "RUNNER=%INSTALL_DIR%\Run-PeechaSync.bat"
if not exist "%RUNNER%" (
    echo PeechaSync is not installed. Run Install PeechaSync.bat
    echo برنامه نصب نیست. Install PeechaSync.bat را اجرا کنید.
    pause
    exit /b 1
)

call "%RUNNER%"
exit /b %ERRORLEVEL%
