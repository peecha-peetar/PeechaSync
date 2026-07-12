@echo off
setlocal EnableExtensions
if "%INSTALL_DIR%"=="" (
    echo ERROR: INSTALL_DIR not set
    exit /b 1
)

set "ERRLOG=%LOCALAPPDATA%\PeechaSync\install-errors.log"
if not exist "%LOCALAPPDATA%\PeechaSync" mkdir "%LOCALAPPDATA%\PeechaSync" 2>nul
echo [%date% %time%] ensure-deps >> "%ERRLOG%"

set "VPY=%INSTALL_DIR%\python\python.exe"
set "USE_VENV=0"
if not exist "%VPY%" (
    set "VPY=%INSTALL_DIR%\.venv\Scripts\python.exe"
    set "USE_VENV=1"
)
if not exist "%VPY%" exit /b 2

call "%~dp0set-python-env.bat" "%VPY%" "%INSTALL_DIR%"
echo [%date% %time%] python=%VPY% >> "%ERRLOG%"

set "IMPORT_RC=1"
if exist "%INSTALL_DIR%\main.pyc" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\verify-main-pyc.ps1" -PythonExe "%VPY%" -MainPyc "%INSTALL_DIR%\main.pyc" -InstallDir "%INSTALL_DIR%" -TimeoutSec 15 >nul 2>&1
    if errorlevel 1 (
        echo [%date% %time%] main.pyc verify failed - will reinstall packages >> "%ERRLOG%"
        set "IMPORT_RC=1"
    ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\test-bootstrap.ps1" -PythonExe "%VPY%" -InstallDir "%INSTALL_DIR%" -TimeoutSec 20 >nul 2>&1
        if errorlevel 1 (
            echo [%date% %time%] bootstrap verify failed >> "%ERRLOG%"
            set "IMPORT_RC=1"
        ) else (
            set "IMPORT_RC=0"
        )
    )
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\test-import.ps1" -PythonExe "%VPY%" -TimeoutSec 15
    set "IMPORT_RC=%ERRORLEVEL%"
)
if "%IMPORT_RC%"=="0" (
    echo [%date% %time%] imports OK >> "%ERRLOG%"
    echo Dependencies OK / پیش‌نیازها به‌روز است.
    exit /b 0
)
type "%TEMP%\peecha-import-test.txt" >> "%ERRLOG%" 2>nul
echo [%date% %time%] import check failed rc=%IMPORT_RC% >> "%ERRLOG%"

set "PACKAGES="
if exist "%INSTALL_DIR%\_packages\*.whl" set "PACKAGES=%INSTALL_DIR%\_packages"
if not defined PACKAGES if exist "%ENGINE_PACKAGES%\*.whl" set "PACKAGES=%ENGINE_PACKAGES%"

if not defined PACKAGES (
    echo [%date% %time%] no offline packages >> "%ERRLOG%"
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0show-message.ps1" -Code install-packages-missing >nul 2>&1
    exit /b 12
)

if not exist "%INSTALL_DIR%\requirements.txt" (
    echo [%date% %time%] missing requirements.txt >> "%ERRLOG%"
    exit /b 3
)

echo Installing packages from installer... / نصب پکیج‌ها از داخل نصاب...
pushd "%INSTALL_DIR%"
call "%~dp0set-python-env.bat" "%VPY%" "%INSTALL_DIR%"
"%VPY%" -m pip install --no-index --find-links "%PACKAGES%" -r requirements.txt >> "%ERRLOG%" 2>&1
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" (
    echo [%date% %time%] offline pip failed rc=%RC% >> "%ERRLOG%"
    exit /b 11
)

call "%~dp0set-python-env.bat" "%VPY%" "%INSTALL_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\test-import.ps1" -PythonExe "%VPY%" -TimeoutSec 15
set "IMPORT_RC=%ERRORLEVEL%"
type "%TEMP%\peecha-import-test.txt" >> "%ERRLOG%" 2>nul
if not "%IMPORT_RC%"=="0" (
    echo [%date% %time%] import still failing after pip rc=%IMPORT_RC% >> "%ERRLOG%"
    if "%USE_VENV%"=="0" if exist "%INSTALL_DIR%\.venv\Scripts\python.exe" (
        set "VPY=%INSTALL_DIR%\.venv\Scripts\python.exe"
        set "USE_VENV=1"
        goto :retry_venv
    )
    exit /b 11
)
if exist "%INSTALL_DIR%\main.pyc" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\test-bootstrap.ps1" -PythonExe "%VPY%" -InstallDir "%INSTALL_DIR%" -TimeoutSec 20 >nul 2>&1
    if errorlevel 1 (
        echo [%date% %time%] bootstrap failed after pip >> "%ERRLOG%"
        type "%TEMP%\peecha-bootstrap-test.txt" >> "%ERRLOG%" 2>nul
        exit /b 11
    )
)
echo [%date% %time%] imports OK after pip >> "%ERRLOG%"
exit /b 0

:retry_venv
echo [%date% %time%] retry pip in .venv >> "%ERRLOG%"
pushd "%INSTALL_DIR%"
call "%~dp0set-python-env.bat" "%VPY%" "%INSTALL_DIR%"
"%VPY%" -m pip install --no-index --find-links "%PACKAGES%" -r requirements.txt >> "%ERRLOG%" 2>&1
popd
call "%~dp0set-python-env.bat" "%VPY%" "%INSTALL_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\test-import.ps1" -PythonExe "%VPY%" -TimeoutSec 15
if not errorlevel 1 exit /b 0
type "%TEMP%\peecha-import-test.txt" >> "%ERRLOG%" 2>nul
exit /b 11
