@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."

echo Fix install.loc BOM + repair python...
powershell -NoProfile -Command "$enc=New-Object System.Text.UTF8Encoding $false; $p='C:\PeechaSync'; [IO.File]::WriteAllText($env:LOCALAPPDATA+'\PeechaSync\install.loc',$p,$enc)"

set "LIB=tools\client-release-deploy\DELIVERY-PeechaSync-1.1.2\PeechaSync-Setup-1.1.2-Portable\PeechaSync-Setup-1.1.2-Portable\_setup\_lib"
if not exist "%LIB%\repair-runtime.bat" ( echo Setup missing & pause & exit /b 1 )

echo Close PeechaSync (python/pythonw) then press a key...
pause >nul

cd /d "%LIB%"
call repair-runtime.bat
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" ( echo OK - run C:\PeechaSync\Run-PeechaSync.bat ) else ( echo failed=%RC% )
pause
exit /b %RC%
