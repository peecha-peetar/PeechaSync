@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~1"
if not defined ROOT set "ROOT=%CD%"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if exist "%ROOT%\patch-launch-env.cmd" (
    call "%ROOT%\patch-launch-env.cmd" "%ROOT%"
)

if exist "%ROOT%\verify-main-pyc.ps1" if exist "%ROOT%\main.pyc" (
    set "PY="
    if exist "%ROOT%\python\python.exe" set "PY=%ROOT%\python\python.exe"
    if not defined PY if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
    if defined PY (
        where powershell >nul 2>&1
        if not errorlevel 1 (
            powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\verify-main-pyc.ps1" -PythonExe "!PY!" -MainPyc "%ROOT%\main.pyc" -InstallDir "%ROOT%" -TimeoutSec 15 >nul 2>&1
            if errorlevel 1 (
                exit /b 1
            )
        )
    )
)

exit /b 0
