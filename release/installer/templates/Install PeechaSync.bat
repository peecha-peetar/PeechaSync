@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0_setup\_lib\setup-gui.ps1" -Mode launcher
exit /b %ERRORLEVEL%
