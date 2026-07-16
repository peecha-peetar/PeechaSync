@echo off
setlocal EnableExtensions EnableDelayedExpansion
call "%~dp0paths.bat"

set "INSTALL_DIR=%DEFAULT_INSTALL%"
call "%~dp0resolve-install-dir.bat" INSTALL_DIR "%DEFAULT_INSTALL%"
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%" 2>nul

if not exist "%LOC_DIR%" mkdir "%LOC_DIR%" 2>nul
echo [%date% %time%] install target=%INSTALL_DIR% engine=%ENGINE_APP%>> "%LOCALAPPDATA%\PeechaSync\install-errors.log"

if not exist "%ENGINE_APP%\main.pyc" (
    echo [%date% %time%] FATAL: setup package incomplete - main.pyc missing in %ENGINE_APP%>> "%LOCALAPPDATA%\PeechaSync\install-errors.log"
    exit /b 1
)

set "PROGRESS=%LOC_DIR%\install-progress.txt"
if not exist "%LOC_DIR%" mkdir "%LOC_DIR%" 2>nul
echo starting> "%PROGRESS%"

if exist "%INSTALL_DIR%\main.pyc" (
    call "%~dp0kill-peecha-processes.bat"
)

call "%~dp0kill-peecha-processes.bat"

echo [install] target=%INSTALL_DIR%
echo [install] clean-old...
echo clean-old>> "%PROGRESS%"
call "%~dp0clean-old-install.bat"
if errorlevel 1 (
    echo [%date% %time%] clean-old failed>> "%LOCALAPPDATA%\PeechaSync\install-errors.log"
    exit /b 1
)

echo [install] copy-app...
echo copy-app>> "%PROGRESS%"
call "%~dp0sync-app-files.bat" "%ENGINE_APP%" "%INSTALL_DIR%"
if errorlevel 1 exit /b 1

:after_copy_app
if exist "%INSTALL_DIR%\python\python.exe" goto :after_deps

if exist "%ENGINE_PACKAGES%" (
    echo copy-packages>> "%PROGRESS%"
    call "%~dp0sync-packages.bat" "%ENGINE_PACKAGES%" "%INSTALL_DIR%\_packages"
    if errorlevel 1 (
        echo [%date% %time%] copy-packages failed>> "%LOCALAPPDATA%\PeechaSync\install-errors.log"
        exit /b 1
    )
)

if not exist "%ENGINE_PYTHON%" goto :use_system_python

echo [install] copy-python - may take 3-5 minutes...
echo copy-python>> "%PROGRESS%"
call "%~dp0sync-bundled-python.bat" "%ENGINE_RUNTIME%\python" "%INSTALL_DIR%\python"
if errorlevel 1 (
    echo [%date% %time%] copy-python failed>> "%LOCALAPPDATA%\PeechaSync\install-errors.log"
    exit /b 1
)
echo deps>> "%PROGRESS%"
pushd "%INSTALL_DIR%"
call "%~dp0ensure-deps.bat"
set "DEPS_RC=!ERRORLEVEL!"
popd
if not "!DEPS_RC!"=="0" exit /b !DEPS_RC!
goto :after_deps

:use_system_python
pushd "%INSTALL_DIR%"
if not exist ".venv\Scripts\python.exe" (
    call "%~dp0find-python.bat"
    if errorlevel 1 (
        popd
        exit /b 1
    )
    %PY_BOOT% -m venv .venv
    if errorlevel 1 (
        popd
        exit /b 1
    )
)
echo deps>> "%PROGRESS%"
call "%~dp0ensure-deps.bat"
set "DEPS_RC=!ERRORLEVEL!"
if not "!DEPS_RC!"=="0" (
    popd
    exit /b !DEPS_RC!
)
popd

:after_deps
echo repair-launch>> "%PROGRESS%"
call "%~dp0repair-launch-env.bat"

echo finalize>> "%PROGRESS%"

set "VERIFY_PY=%INSTALL_DIR%\python\python.exe"
if not exist "%VERIFY_PY%" set "VERIFY_PY=%INSTALL_DIR%\.venv\Scripts\python.exe"
if exist "%VERIFY_PY%" (
    call "%~dp0set-python-env.bat" "%VERIFY_PY%" "%INSTALL_DIR%"
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\test-import.ps1" -PythonExe "%VERIFY_PY%" -TimeoutSec 20
    if errorlevel 1 (
        type "%LOCALAPPDATA%\PeechaSync\install-errors.log" >nul 2>&1
        echo [%date% %time%] post-install import verify failed >> "%LOCALAPPDATA%\PeechaSync\install-errors.log"
        type "%TEMP%\peecha-import-test.txt" >> "%LOCALAPPDATA%\PeechaSync\install-errors.log" 2>nul
        exit /b 11
    )
    if exist "%INSTALL_DIR%\main.pyc" (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\verify-main-pyc.ps1" -PythonExe "%VERIFY_PY%" -MainPyc "%INSTALL_DIR%\main.pyc" -InstallDir "%INSTALL_DIR%" -TimeoutSec 15
        if errorlevel 1 (
            echo [%date% %time%] post-install main.pyc verify failed >> "%LOCALAPPDATA%\PeechaSync\install-errors.log"
            type "%TEMP%\peecha-main-pyc-test.txt" >> "%LOCALAPPDATA%\PeechaSync\install-errors.log" 2>nul
            exit /b 11
        )
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\engine\app\test-bootstrap.ps1" -PythonExe "%VERIFY_PY%" -InstallDir "%INSTALL_DIR%" -TimeoutSec 20
        if errorlevel 1 (
            echo [%date% %time%] post-install bootstrap verify failed >> "%LOCALAPPDATA%\PeechaSync\install-errors.log"
            type "%TEMP%\peecha-bootstrap-test.txt" >> "%LOCALAPPDATA%\PeechaSync\install-errors.log" 2>nul
            exit /b 11
        )
        echo [%date% %time%] main.pyc OK >> "%LOCALAPPDATA%\PeechaSync\install-errors.log"
    )
)

if exist "%PKG_ICON%" (
    copy /y "%PKG_ICON%" "%INSTALL_DIR%\PeechaSync.ico" >nul 2>&1
    if not exist "%INSTALL_DIR%\sync_app\core" mkdir "%INSTALL_DIR%\sync_app\core" 2>nul
    copy /y "%PKG_ICON%" "%INSTALL_DIR%\sync_app\core\PeechaSync.ico" >nul 2>&1
    copy /y "%PKG_ICON%" "%INSTALL_DIR%\sync_app\core\Peecha_logo.ico" >nul 2>&1
)

if not exist "%LOC_DIR%" mkdir "%LOC_DIR%" 2>nul
powershell -NoProfile -Command "$p=[System.IO.Path]::GetFullPath('%INSTALL_DIR%'); $enc=New-Object System.Text.UTF8Encoding $false; [System.IO.File]::WriteAllText('%LOC_FILE%', $p, $enc)"

if exist "%PKG_ROOT%\VERSION.txt" (
    copy /y "%PKG_ROOT%\VERSION.txt" "%INSTALL_DIR%\VERSION.txt" >nul 2>&1
)

set "EXPECTED_VER="
if exist "%PKG_ROOT%\VERSION.txt" (
    for /f "usebackq delims=" %%V in ("%PKG_ROOT%\VERSION.txt") do set "EXPECTED_VER=%%V"
)

if exist "%INSTALL_DIR%\peecha-version-refresh.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_DIR%\peecha-version-refresh.ps1" -InstallRoot "%INSTALL_DIR%"
)

if exist "%INSTALL_DIR%\Assert-InstalledVersion.ps1" if exist "%PKG_ROOT%\VERSION.txt" (
    for /f "usebackq delims=" %%V in ("%PKG_ROOT%\VERSION.txt") do (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_DIR%\Assert-InstalledVersion.ps1" -InstallRoot "%INSTALL_DIR%" -ExpectedVersion "%%V"
        if errorlevel 1 exit /b 12
    )
)

if not exist "%INSTALL_DIR%\Run-PeechaSync.bat" exit /b 1

for %%F in (Run-PeechaSync.bat launch-gui.cmd launch-gui.ps1 patch-launch-env.cmd repair-launch-env.cmd set-python-env.bat test-import.ps1 test-bootstrap.ps1 verify-main-pyc.ps1 Launch-PeechaSync.vbs Force-CleanProgramFiles.ps1 Assert-InstalledVersion.ps1 kill-peecha-processes.ps1) do (
    if exist "%ENGINE_APP%\%%F" copy /y "%ENGINE_APP%\%%F" "%INSTALL_DIR%\%%F" >nul 2>&1
)
findstr /C:"launcher=1.1.11" "%INSTALL_DIR%\Run-PeechaSync.bat" >nul 2>&1
if errorlevel 1 (
    echo [%date% %time%] WARN launcher not updated >> "%LOCALAPPDATA%\PeechaSync\install-errors.log"
)

echo done>> "%PROGRESS%"

del /f /q "%LOCALAPPDATA%\PeechaSync\pending-update.json" 2>nul
del /f /q "%LOCALAPPDATA%\PeechaSync\update-apply-failed.json" 2>nul
if exist "%TEMP%\PeechaSync-updates" rd /s /q "%TEMP%\PeechaSync-updates" 2>nul

exit /b 0
