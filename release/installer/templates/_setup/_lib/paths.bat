@echo off
set "PKG_ROOT=%~dp0.."
for %%I in ("%PKG_ROOT%") do set "PKG_ROOT=%%~fI"
set "PKG_ICON=%PKG_ROOT%\PeechaSync.ico"
set "ENGINE_APP=%PKG_ROOT%\engine\app"
set "ENGINE_PACKAGES=%PKG_ROOT%\engine\packages"
set "ENGINE_RUNTIME=%PKG_ROOT%\engine\runtime"
set "ENGINE_PYTHON=%ENGINE_RUNTIME%\python\python.exe"
set "DEFAULT_INSTALL=C:\PeechaSync"
set "LOC_DIR=%LOCALAPPDATA%\PeechaSync"
set "LOC_FILE=%LOC_DIR%\install.loc"
call "%~dp0resolve-desktop.bat" 2>nul
if not defined SHORTCUT (
    set "DESKTOP=%USERPROFILE%\Desktop"
    set "SHORTCUT=%DESKTOP%\PeechaSync.lnk"
)
