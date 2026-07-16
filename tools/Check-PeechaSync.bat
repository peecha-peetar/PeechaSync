@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo PeechaSync check...
echo.

set "REPORT=%~dp0PeechaSync-diagnostic-report.txt"
set "INSTALL=C:\PeechaSync"
set "APPLOG=%LOCALAPPDATA%\PeechaSync"
set "LOC=%APPLOG%\install.loc"

if exist "%LOC%" (
    for /f "usebackq delims=" %%D in ("%LOC%") do set "INSTALL=%%D"
)

> "%REPORT%" echo ========================================
>> "%REPORT%" echo PeechaSync diagnostic report
>> "%REPORT%" echo ========================================
>> "%REPORT%" echo Time: %date% %time%
>> "%REPORT%" echo PC: %COMPUTERNAME%
>> "%REPORT%" echo User: %USERNAME%
>> "%REPORT%" echo Report folder: %~dp0
>> "%REPORT%" echo.

echo [1/5] Windows...
>> "%REPORT%" echo --- Windows ---
ver >> "%REPORT%" 2>&1

echo [2/5] Python...
>> "%REPORT%" echo.
>> "%REPORT%" echo --- Python ---
set "PYOK=0"
set "PYEXE="
call :RunTimed 3 where python
if exist "%TEMP%\peecha-last.txt" (
    for /f "usebackq delims=" %%P in ("%TEMP%\peecha-last.txt") do (
        if not defined PYEXE set "PYEXE=%%P"
    )
    type "%TEMP%\peecha-last.txt" >> "%REPORT%"
)
for %%X in (
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
) do (
    if "%PYOK%"=="0" if exist %%X set "PYEXE=%%~X"
)
if defined PYEXE (
    call :RunTimed 5 "%PYEXE%" -c "import sys; print(sys.version); print(sys.executable)"
    if exist "%TEMP%\peecha-last.txt" (
        findstr /r "3\.1[0-9]" "%TEMP%\peecha-last.txt" >nul 2>&1
        if not errorlevel 1 set "PYOK=1"
        type "%TEMP%\peecha-last.txt" >> "%REPORT%"
    )
)
if "%PYOK%"=="0" >> "%REPORT%" echo FAIL: system Python not in PATH

echo [3/5] Install folder...
>> "%REPORT%" echo.
>> "%REPORT%" echo --- Install folder ---
>> "%REPORT%" echo Path: %INSTALL%
if exist "%INSTALL%" (
    >> "%REPORT%" echo OK folder exists
) else (
    >> "%REPORT%" echo FAIL folder not found
)
for %%F in (main.pyc main.py Run-PeechaSync.bat) do (
    if exist "%INSTALL%\%%F" (>> "%REPORT%" echo OK %%F) else (>> "%REPORT%" echo MISSING %%F)
)
if exist "%INSTALL%\.peecha-pyc-only" (
    if not exist "%INSTALL%\main.py" >> "%REPORT%" echo OK main.py not needed (pyc-only install)
)
if exist "%INSTALL%\VERSION.txt" (
    for /f "usebackq delims=" %%V in ("%INSTALL%\VERSION.txt") do >> "%REPORT%" echo Installed version: %%V
) else (
    >> "%REPORT%" echo MISSING VERSION.txt
)
if exist "%INSTALL%\Run-PeechaSync.bat" (
    findstr /C:"launcher=" "%INSTALL%\Run-PeechaSync.bat" >> "%REPORT%" 2>nul
) else (
    >> "%REPORT%" echo MISSING Run-PeechaSync.bat launcher marker
)
if exist "%INSTALL%\python\python.exe" (
    >> "%REPORT%" echo OK python\python.exe
) else (
    >> "%REPORT%" echo MISSING python\python.exe
)
if exist "%INSTALL%\python\Lib\site-packages\PyQt5" (
    >> "%REPORT%" echo OK python site-packages\PyQt5
) else (
    >> "%REPORT%" echo MISSING python site-packages\PyQt5
)
if exist "%INSTALL%\_packages\*.whl" (
    >> "%REPORT%" echo OK _packages wheels folder
) else (
    >> "%REPORT%" echo MISSING _packages wheels
)
if exist "%INSTALL%\.venv\Scripts\python.exe" (
    >> "%REPORT%" echo OK .venv\Scripts\python.exe
) else (
    >> "%REPORT%" echo MISSING .venv\Scripts\python.exe
)

echo [4/5] Desktop shortcut...
>> "%REPORT%" echo.
>> "%REPORT%" echo --- Desktop shortcut ---
set "SHORTCUT="
for %%D in ("%USERPROFILE%\Desktop" "%OneDrive%\Desktop" "%USERPROFILE%\OneDrive\Desktop" "%PUBLIC%\Desktop") do (
    if exist %%D\PeechaSync.lnk set "SHORTCUT=%%~D\PeechaSync.lnk"
)
if defined SHORTCUT (
    >> "%REPORT%" echo OK !SHORTCUT!
    for %%I in ("!SHORTCUT!") do >> "%REPORT%" echo Size: %%~zI bytes
) else (
    >> "%REPORT%" echo MISSING PeechaSync.lnk
    >> "%REPORT%" echo Checked: %USERPROFILE%\Desktop
    if defined OneDrive >> "%REPORT%" echo Checked: %OneDrive%\Desktop
)

echo [5/5] App packages...
>> "%REPORT%" echo.
>> "%REPORT%" echo --- Package imports ---
set "VPY=%INSTALL%\python\python.exe"
set "IMPORT_PS=%INSTALL%\test-import.ps1"
if not exist "%IMPORT_PS%" set "IMPORT_PS=%~dp0test-import.ps1"
if not exist "%VPY%" set "VPY=%INSTALL%\.venv\Scripts\python.exe"
if not exist "%VPY%" (
    >> "%REPORT%" echo SKIP no install python
    goto :log
)
>> "%REPORT%" echo Python: %VPY%
if exist "%INSTALL%\set-python-env.bat" (
    call "%INSTALL%\set-python-env.bat" "%VPY%"
) else if exist "%~dp0set-python-env.bat" (
    call "%~dp0set-python-env.bat" "%VPY%"
)
if exist "%IMPORT_PS%" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%IMPORT_PS%" -PythonExe "%VPY%" -TimeoutSec 15
    set "IMPORT_RC=!ERRORLEVEL!"
) else (
    set "IMPORT_RC=1"
)
if "!IMPORT_RC!"=="0" (
    >> "%REPORT%" echo OK import test
) else if "!IMPORT_RC!"=="2" (
    >> "%REPORT%" echo TIMEOUT import test
) else (
    >> "%REPORT%" echo FAIL import test
)
if exist "%TEMP%\peecha-import-test.txt" (
    type "%TEMP%\peecha-import-test.txt" >> "%REPORT%"
)

>> "%REPORT%" echo.
>> "%REPORT%" echo --- main.pyc load test ---
set "VERIFY_PS=%INSTALL%\verify-main-pyc.ps1"
if not exist "%VERIFY_PS%" set "VERIFY_PS=%~dp0verify-main-pyc.ps1"
if not exist "%VPY%" (
    >> "%REPORT%" echo SKIP no install python
) else if not exist "%INSTALL%\main.pyc" (
    >> "%REPORT%" echo SKIP no main.pyc
) else if exist "%VERIFY_PS%" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%VERIFY_PS%" -PythonExe "%VPY%" -MainPyc "%INSTALL%\main.pyc" -TimeoutSec 15
    set "PYC_RC=!ERRORLEVEL!"
    if "!PYC_RC!"=="0" (
        >> "%REPORT%" echo OK main.pyc loads with bundled python
    ) else if "!PYC_RC!"=="2" (
        >> "%REPORT%" echo TIMEOUT main.pyc test
    ) else (
        >> "%REPORT%" echo FAIL main.pyc (Bad magic or corrupt - reinstall with latest Setup ZIP option 1)
    )
    if exist "%TEMP%\peecha-main-pyc-test.txt" type "%TEMP%\peecha-main-pyc-test.txt" >> "%REPORT%"
) else (
    >> "%REPORT%" echo SKIP verify-main-pyc.ps1 not found
)

>> "%REPORT%" echo.
    >> "%REPORT%" echo --- App bootstrap test ---
if not exist "%VPY%" (
    >> "%REPORT%" echo SKIP no install python
) else if exist "%INSTALL%\test-bootstrap.ps1" (
    set "PYTHONPATH=%INSTALL%"
    powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALL%\test-bootstrap.ps1" -PythonExe "%VPY%" -InstallDir "%INSTALL%" -TimeoutSec 20
    set "BOOT_RC=!ERRORLEVEL!"
    if "!BOOT_RC!"=="0" (
        >> "%REPORT%" echo OK app bootstrap
    ) else if "!BOOT_RC!"=="2" (
        >> "%REPORT%" echo TIMEOUT app bootstrap
    ) else (
        >> "%REPORT%" echo FAIL app bootstrap - run Install PeechaSync.bat option 1
    )
    if exist "%TEMP%\peecha-bootstrap-test.txt" type "%TEMP%\peecha-bootstrap-test.txt" >> "%REPORT%"
) else (
    set "PYTHONPATH=%INSTALL%"
    pushd "%INSTALL%"
    call :RunTimed 15 "%VPY%" -c "import os,sys; r=r'%INSTALL%'; sys.path.insert(0,r); os.chdir(r); from sync_app.core.peecha_launcher import main; print('OK peecha_launcher')"
    popd
    if exist "%TEMP%\peecha-last.txt" (
        findstr /i "OK peecha_launcher" "%TEMP%\peecha-last.txt" >nul 2>&1
        if errorlevel 1 (
            >> "%REPORT%" echo FAIL app bootstrap
        ) else (
            >> "%REPORT%" echo OK app bootstrap
        )
        type "%TEMP%\peecha-last.txt" >> "%REPORT%"
    ) else (
        >> "%REPORT%" echo TIMEOUT app bootstrap
    )
)

:log
>> "%REPORT%" echo.
>> "%REPORT%" echo --- startup-errors.log ---
if exist "%APPLOG%\startup-errors.log" (
    type "%APPLOG%\startup-errors.log" >> "%REPORT%"
) else (
    >> "%REPORT%" echo not found
)
>> "%REPORT%" echo.
>> "%REPORT%" echo --- install-errors.log ---
if exist "%APPLOG%\install-errors.log" (
    type "%APPLOG%\install-errors.log" >> "%REPORT%"
) else (
    >> "%REPORT%" echo not found
)

>> "%REPORT%" echo.
>> "%REPORT%" echo ========================================
>> "%REPORT%" echo Report: %REPORT%
>> "%REPORT%" echo Send this file to Peecha support.
>> "%REPORT%" echo ========================================

echo.
echo Done.
echo Report: %REPORT%
start "" notepad "%REPORT%"
pause
exit /b 0

:RunTimed
set "WAIT=%~1"
shift
set "OUT=%TEMP%\peecha-last.txt"
del /f /q "%OUT%" >nul 2>&1
start "" /min cmd /c %* >"%OUT%" 2>&1
timeout /t %WAIT% /nobreak >nul
exit /b 0
