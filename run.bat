@echo off
chcp 65001 >nul 2>&1
REM PeechaSync Windows Batch Launcher

cd /d "%~dp0"
echo PeechaSync launcher...
set "PY=%~dp0.venv\Scripts\python.exe"
set "EXIT_CODE=0"
set "VENV_REBUILT=0"

if /I "%PEECHA_SKIP_GIT%"=="1" goto :skip_git_msg
if exist ".peecha-release" goto :skip_git_msg
if not exist ".git" goto :skip_git_msg

echo Updating from GitHub...
git fetch origin main
if errorlevel 1 (
    echo git fetch failed - continuing with local files.
) else (
    git checkout -B main origin/main
    if errorlevel 1 (
        echo git checkout failed - continuing with local files.
    )
)
echo.
goto :after_git

:skip_git_msg
if /I "%PEECHA_SKIP_GIT%"=="1" (
    echo Git update skipped ^(PEECHA_SKIP_GIT=1^).
) else if exist ".peecha-release" (
    echo Release package - skip git update.
) else (
    echo No .git folder - skip git update.
)
echo.

:after_git
if not exist "%PY%" goto :create_venv
goto :ensure_deps

:create_venv
echo .venv not found - creating virtual environment...
py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || python -m venv .venv
if errorlevel 1 (
    echo Failed to create .venv. Install Python 3.11+ and try again.
    pause
    exit /b 1
)

:ensure_deps
if not exist "%PY%" (
    echo ERROR: .venv\Scripts\python.exe not found.
    pause
    exit /b 1
)

"%PY%" -c "import PyQt5" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    "%PY%" -m pip install --upgrade pip
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo pip install failed.
        pause
        exit /b 1
    )
)

"%PY%" -c "import PyQt5" >nul 2>&1
if errorlevel 1 (
    if "%VENV_REBUILT%"=="1" (
        echo ERROR: PyQt5 is still missing after rebuild.
        pause
        exit /b 1
    )
    echo Broken .venv - rebuilding...
    set "VENV_REBUILT=1"
    rmdir /s /q ".venv" 2>nul
    goto :create_venv
)

echo Using:
"%PY%" -c "import sys; print(sys.executable)"
"%PY%" -c "from sync_app.core.app_version import APP_VERSION; print('Version:', APP_VERSION)" 2>nul
echo.

:run_app
echo PeechaSync GUI is starting...
"%PY%" -u main.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo PeechaSync exited with error %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
