@echo off
set "DESKTOP=%USERPROFILE%\Desktop"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"
if not exist "%DESKTOP%" mkdir "%DESKTOP%" 2>nul
set "SHORTCUT=%DESKTOP%\PeechaSync.lnk"
