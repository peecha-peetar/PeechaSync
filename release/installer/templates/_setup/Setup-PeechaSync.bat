@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0_lib\setup-gui.ps1" -Mode install
exit /b %ERRORLEVEL%
