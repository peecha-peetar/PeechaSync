@echo off
ping -n 1 -w 2500 1.1.1.1 >nul 2>&1
if not errorlevel 1 exit /b 0
ping -n 1 -w 2500 8.8.8.8 >nul 2>&1
if not errorlevel 1 exit /b 0
where curl >nul 2>&1
if errorlevel 1 exit /b 1
curl -s -o nul --connect-timeout 5 https://pypi.org/ >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0
