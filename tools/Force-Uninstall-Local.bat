@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title PeechaSync - Force uninstall

echo ============================================================
echo  PeechaSync - حذف کامل نسخه نصب‌شده
echo  Close PeechaSync first / برنامه را ببندید
echo ============================================================
echo.

set "LIB=release\installer\templates\_setup\_lib"
if not exist "%LIB%\full-uninstall.ps1" (
    echo full-uninstall.ps1 not found. Run from PeechaSync source folder.
    pause
    exit /b 1
)

call "%LIB%\uninstall-app.bat"
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
    echo.
    echo OK - uninstall complete.
    echo For fresh install: extract Setup ZIP and press button 1.
) else (
    echo.
    echo FAILED - see %LOCALAPPDATA%\PeechaSync\uninstall-last.log
)

echo.
pause
exit /b %RC%
