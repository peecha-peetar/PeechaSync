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
set "VPY=%INSTALL%\.venv\Scripts\python.exe"
if not exist "%VPY%" (
    >> "%REPORT%" echo SKIP no venv python
    goto :log
)
call :RunTimed 12 "%VPY%" -c "import PyQt5, pyodbc, requests, woocommerce, cryptography, psutil; print('OK all imports')"
if exist "%TEMP%\peecha-last.txt" (
    findstr /i "OK all imports" "%TEMP%\peecha-last.txt" >nul 2>&1
    if errorlevel 1 (
        >> "%REPORT%" echo FAIL import test
    )
    type "%TEMP%\peecha-last.txt" >> "%REPORT%"
) else (
    >> "%REPORT%" echo TIMEOUT import test
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
