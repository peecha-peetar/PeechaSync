@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "LOG_FILE=%~1"
set "PYREL=%~2"
set "ROOT=%CD%"

if not defined PYREL set "PYREL=python\pythonw.exe"
if not exist "%ROOT%\%PYREL%" set "PYREL=python\python.exe"
set "PYFULL=%ROOT%\%PYREL%"
if not exist "%PYFULL%" exit /b 4

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

start "" /MIN "%PYFULL%" -u "%MAIN%"
ping 127.0.0.1 -n 3 >nul

set "RUNNING=0"
for /f "usebackq delims=" %%p in (`wmic process where "(name='python.exe' or name='pythonw.exe') and CommandLine like '%%-u%%' and (CommandLine like '%%main.pyc%%' or CommandLine like '%%main.py%%')" get ProcessId 2^>nul ^| findstr /r "[0-9]"`) do (
    set "RUNNING=1"
    if defined LOG_FILE echo [%date% %time%] pid %%p>>"%LOG_FILE%"
    goto :done
)
:done
if "%RUNNING%"=="1" exit /b 0

if defined LOG_FILE echo [%date% %time%] process exited early>>"%LOG_FILE%"
set "OUT=%TEMP%\peecha-launch-out.txt"
set "ERR=%TEMP%\peecha-launch-err.txt"
del /f /q "%OUT%" "%ERR%" 2>nul
set "PYTHONPATH=%ROOT%"
"%PYFULL%" -u "%MAIN%" 1>"%OUT%" 2>"%ERR%"
set "RC=!ERRORLEVEL!"
if exist "%OUT%" (
    for /f "usebackq delims=" %%L in ("%OUT%") do if defined LOG_FILE echo [python-out] %%L>>"%LOG_FILE%"
)
if exist "%ERR%" (
    for /f "usebackq delims=" %%L in ("%ERR%") do if defined LOG_FILE echo [python-err] %%L>>"%LOG_FILE%"
)
if defined LOG_FILE echo [%date% %time%] capture exit code=!RC!>>"%LOG_FILE%"
exit /b 5
