@echo off
setlocal EnableExtensions
set "PYEXE=%~1"
set "INSTALL_ROOT=%~2"
if not exist "%PYEXE%" exit /b 1

for %%I in ("%PYEXE%") do set "PYDIR=%%~dpI"
set "PATH=%PYDIR%;%PYDIR%Scripts;%PATH%"

if defined INSTALL_ROOT (
    if "%INSTALL_ROOT:~-1%"=="\" set "INSTALL_ROOT=%INSTALL_ROOT:~0,-1%"
    set "PYTHONPATH=%INSTALL_ROOT%"
)

echo %PYDIR% | findstr /i "\\python\\" >nul 2>&1
if not errorlevel 1 set "PYTHONHOME=%PYDIR:~0,-1%"

echo %PYDIR% | findstr /i "\\Scripts\\" >nul 2>&1
if not errorlevel 1 (
    for %%I in ("%PYDIR%..") do set "SITE=%%~fI\Lib\site-packages"
) else (
    set "SITE=%PYDIR%Lib\site-packages"
)

set "QT_BIN=%SITE%\PyQt5\Qt5\bin"
set "QT_PLUGINS=%SITE%\PyQt5\Qt5\plugins"
if exist "%QT_BIN%" set "PATH=%QT_BIN%;%PATH%"
if exist "%QT_PLUGINS%" set "QT_PLUGIN_PATH=%QT_PLUGINS%"
set "QT_QPA_PLATFORM=windows"

endlocal & (
    set "PATH=%PATH%"
    if defined PYTHONHOME set "PYTHONHOME=%PYTHONHOME%"
    if defined PYTHONPATH set "PYTHONPATH=%PYTHONPATH%"
    if defined QT_PLUGIN_PATH set "QT_PLUGIN_PATH=%QT_PLUGIN_PATH%"
    set "QT_QPA_PLATFORM=windows"
)
exit /b 0
