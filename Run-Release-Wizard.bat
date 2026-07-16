@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title PeechaSync Release Wizard
mode con: cols=78 lines=38 >nul 2>&1

set "ROOT=%~dp0"
set "PS1=%ROOT%tools\Release-Wizard.ps1"
set "LANG=auto"
set "USE_WT=0"

if /I "%~1"=="-fa" set "LANG=fa"
if /I "%~1"=="-en" set "LANG=en"
if /I "%~1"=="--fa" set "LANG=fa"
if /I "%~1"=="--en" set "LANG=en"

if not exist "%PS1%" (
    echo ERROR: tools\Release-Wizard.ps1 not found
    pause
    exit /b 1
)

REM Windows Terminal can show Persian; classic CMD font cannot (shows ???)
if /I "%LANG%"=="fa" (
    where wt >nul 2>&1
    if errorlevel 1 (
        echo Windows Terminal not found - using English UI
        echo.
        set "LANG=en"
    ) else (
        set "USE_WT=1"
    )
) else if /I not "%LANG%"=="en" (
    where wt >nul 2>&1
    if not errorlevel 1 set "USE_WT=1"
)

if "%USE_WT%"=="1" (
    if /I "%LANG%"=="auto" set "LANG=fa"
    echo Opening Windows Terminal - Persian UI
    echo.
    wt -w 0 nt -d "%CD%" --title "PeechaSync Release Wizard" powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%PS1%" -Lang %LANG%
    exit /b 0
)

if /I "%LANG%"=="auto" set "LANG=en"
echo UI: English ^(this console cannot show Persian^)
echo For Persian: install Windows Terminal, or run  Run-Release-Wizard.bat -fa
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -Lang %LANG%
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo OK
) else (
    echo FAILED exit %RC%
)
pause
exit /b %RC%
