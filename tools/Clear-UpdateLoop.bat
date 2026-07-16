@echo off
chcp 65001 >nul
echo Stopping PeechaSync update loop...
taskkill /F /IM pythonw.exe /T 2>nul
taskkill /F /IM python.exe /T 2>nul
del /f /q "%LOCALAPPDATA%\PeechaSync\pending-update.json" 2>nul
del /f /q "%LOCALAPPDATA%\PeechaSync\update-apply-failed.json" 2>nul
del /f /q "%LOCALAPPDATA%\PeechaSync\update-apply-attempts.json" 2>nul
if exist "%TEMP%\PeechaSync-updates" rd /s /q "%TEMP%\PeechaSync-updates" 2>nul
echo Done. Now run Setup ZIP: button 3 then button 1.
pause
