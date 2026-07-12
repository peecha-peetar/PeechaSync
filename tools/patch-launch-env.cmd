@echo off
setlocal EnableExtensions
set "ROOT=%~1"
if not defined ROOT set "ROOT=%CD%"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
if exist "%ROOT%" set "PYTHONPATH=%ROOT%"
endlocal & (
    if defined PYTHONPATH set "PYTHONPATH=%PYTHONPATH%"
)
exit /b 0
