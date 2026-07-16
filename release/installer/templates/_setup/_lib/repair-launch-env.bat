@echo off
setlocal EnableExtensions
call "%~dp0paths.bat"

set "INSTALL_DIR=%DEFAULT_INSTALL%"
if exist "%LOC_FILE%" (
    for /f "usebackq delims=" %%D in ("%LOC_FILE%") do set "INSTALL_DIR=%%D"
)

if not exist "%INSTALL_DIR%" exit /b 0
if not exist "%ENGINE_APP%" exit /b 0

echo [%date% %time%] repair-launch-env >> "%LOC_DIR%\install-errors.log" 2>nul

for %%F in (
    Run-PeechaSync.bat
    launch-gui.cmd
    launch-gui.ps1
    patch-launch-env.cmd
    set-python-env.bat
    test-import.ps1
    test-bootstrap.ps1
    verify-main-pyc.ps1
) do (
    if exist "%ENGINE_APP%\%%F" (
        copy /y "%ENGINE_APP%\%%F" "%INSTALL_DIR%\%%F" >nul 2>&1
    )
)

exit /b 0
