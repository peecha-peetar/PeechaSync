@echo off
setlocal EnableExtensions
set "CODE=%~1"
if "%CODE%"=="" set "CODE=internet-packages"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0show-user-message.ps1" -Code %CODE% 2>nul
if errorlevel 1 (
    mshta "javascript:var sh=new ActiveXObject('WScript.Shell');sh.Popup('PeechaSync could not start (%CODE%).\r\nLog: %LOCALAPPDATA%\\PeechaSync\\startup-errors.log',0,'PeechaSync',48);close()"
)
exit /b 1
