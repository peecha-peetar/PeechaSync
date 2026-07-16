@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "LOG_FILE=%~1"
set "PYREL=%~2"
set "ROOT=%CD%"

if not defined PYREL set "PYREL=python\pythonw.exe"
if not exist "%ROOT%\%PYREL%" set "PYREL=python\pythonw.exe"
if not exist "%ROOT%\%PYREL%" set "PYREL=python\python.exe"
set "PYFULL=%ROOT%\%PYREL%"
if not exist "%PYFULL%" exit /b 4

if exist "%ROOT%\launch-gui.ps1" (
    where powershell >nul 2>&1
    if not errorlevel 1 (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\launch-gui.ps1" -LogFile "%LOG_FILE%"
        exit /b %ERRORLEVEL%
    )
)

if exist "%ROOT%\patch-launch-env.cmd" (
    call "%ROOT%\patch-launch-env.cmd" "%ROOT%"
) else (
    set "PYTHONPATH=%ROOT%"
)

set "MAIN="
if exist "%ROOT%\.peecha-pyc-only" if exist "%ROOT%\main.pyc" set "MAIN=main.pyc"
if not defined MAIN if exist "%ROOT%\main.py" set "MAIN=main.py"
if not defined MAIN if exist "%ROOT%\main.pyc" set "MAIN=main.pyc"
if not defined MAIN exit /b 2

if defined LOG_FILE echo [%date% %time%] spawn try %PYFULL% -u %MAIN%>>"%LOG_FILE%"

start "" /B "%PYFULL%" -u "%MAIN%"
ping 127.0.0.1 -n 3 >nul

set "RUNNING=0"
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "Get-CimInstance Win32_Process -EA 0 | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*-u*' -and ($_.CommandLine -like '*main.pyc*' -or $_.CommandLine -like '*main.py*') } | Select-Object -ExpandProperty ProcessId"`) do (
    set "RUNNING=1"
    if defined LOG_FILE echo [%date% %time%] pid %%p>>"%LOG_FILE%"
    goto :done
)
:done
if "%RUNNING%"=="1" exit /b 0

if defined LOG_FILE echo [%date% %time%] process exited early - retry hidden>>"%LOG_FILE%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\launch-gui.ps1" -LogFile "%LOG_FILE%" 2>nul
exit /b %ERRORLEVEL%
