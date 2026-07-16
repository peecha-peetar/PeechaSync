@echo off
setlocal EnableExtensions EnableDelayedExpansion
call "%~dp0paths.bat"

set "INSTALL_DIR=%DEFAULT_INSTALL%"
call "%~dp0resolve-install-dir.bat" INSTALL_DIR "%DEFAULT_INSTALL%"

set "LOG=%LOCALAPPDATA%\PeechaSync\install-errors.log"
set "PROGRESS=%LOC_DIR%\install-progress.txt"
if not exist "%LOC_DIR%" mkdir "%LOC_DIR%" 2>nul

echo [%date% %time%] repair-runtime start install=%INSTALL_DIR%>> "%LOG%"

call "%~dp0kill-peecha-processes.bat"

if not exist "%INSTALL_DIR%\sync_app\core\peecha_launcher.pyc" (
    echo [%date% %time%] repair-runtime: sync_app incomplete - need full install>> "%LOG%"
    exit /b 2
)

echo repair-runtime>> "%PROGRESS%"

if exist "%ENGINE_PYTHON%" (
    echo copy-python>> "%PROGRESS%"
    call "%~dp0sync-bundled-python.bat" "%ENGINE_RUNTIME%\python" "%INSTALL_DIR%\python"
    if errorlevel 1 (
        echo [%date% %time%] repair-runtime: python copy failed>> "%LOG%"
        exit /b 1
    )
) else (
    echo [%date% %time%] repair-runtime: bundled python missing in setup>> "%LOG%"
    exit /b 3
)

if exist "%ENGINE_PACKAGES%" (
    echo copy-packages>> "%PROGRESS%"
    call "%~dp0sync-packages.bat" "%ENGINE_PACKAGES%" "%INSTALL_DIR%\_packages"
)

echo deps>> "%PROGRESS%"
set "INSTALL_DIR=%INSTALL_DIR%"
pushd "%INSTALL_DIR%"
call "%~dp0ensure-deps.bat"
set "DEPS_RC=!ERRORLEVEL!"
popd
if not "!DEPS_RC!"=="0" (
    echo [%date% %time%] repair-runtime: ensure-deps failed rc=%DEPS_RC%>> "%LOG%"
    exit /b 1
)

call "%~dp0repair-launch-env.bat"

if exist "%PKG_ROOT%\VERSION.txt" (
    copy /y "%PKG_ROOT%\VERSION.txt" "%INSTALL_DIR%\VERSION.txt" >nul 2>&1
)

set "VERIFY_PY=%INSTALL_DIR%\python\python.exe"
if exist "%VERIFY_PY%" (
    call "%~dp0set-python-env.bat" "%VERIFY_PY%" "%INSTALL_DIR%"
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\test-import.ps1" -PythonExe "%VERIFY_PY%" -TimeoutSec 20
    if errorlevel 1 (
        echo [%date% %time%] repair-runtime: import verify failed>> "%LOG%"
        exit /b 11
    )
)

echo done>> "%PROGRESS%"
echo [%date% %time%] repair-runtime ok>> "%LOG%"
exit /b 0
