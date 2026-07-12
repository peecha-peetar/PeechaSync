@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0..\_lib\setup-gui.ps1" -Mode menu
exit /b %ERRORLEVEL%
