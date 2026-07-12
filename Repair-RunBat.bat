@echo off
cd /d "%~dp0"
echo Restore core launcher files from GitHub...
if not exist ".git" (
    echo ERROR: .git folder not found.
    pause
    exit /b 1
)
git fetch origin main
git checkout origin/main -- run.bat Repair-RunBat.bat main.py sync_app/core/peecha_launcher.py
if errorlevel 1 (
    echo git checkout failed.
    pause
    exit /b 1
)
for %%F in (run.bat main.py sync_app\core\peecha_launcher.py) do (
    if exist "%%F" (
        for %%A in ("%%F") do echo %%F - %%~zA bytes
    ) else (
        echo MISSING: %%F
    )
)
echo.
echo Done. Now run: run.bat
pause
