@echo off

setlocal EnableExtensions EnableDelayedExpansion

if /I not "%~1"=="internal" (
    if exist "%~dp0Launch-PeechaSync.vbs" (
        start "" /B wscript.exe //nologo "%~dp0Launch-PeechaSync.vbs"
        exit /b 0
    )
)

chcp 65001 >nul 2>&1



set "LOG_DIR=%LOCALAPPDATA%\PeechaSync"

set "LOG_FILE=%LOG_DIR%\startup-errors.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul

echo [%date% %time%] Run-PeechaSync started >> "%LOG_FILE%"

echo [%date% %time%] launcher=1.1.11 >> "%LOG_FILE%"



set "ROOT=%~dp0"

if exist "%LOCALAPPDATA%\PeechaSync\install.loc" (

    for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$p=(Get-Content -LiteralPath $env:LOCALAPPDATA+'\PeechaSync\install.loc' -Raw -Encoding UTF8).Trim().Trim([char]0xFEFF); if($p){$p}"`) do (

        if exist "%%P\sync_app" set "ROOT=%%P\"

    )

)



cd /d "%ROOT%" 2>>"%LOG_FILE%"

if errorlevel 1 (

    echo [%date% %time%] cd failed: %ROOT% >> "%LOG_FILE%"

    call "%ROOT%show-startup-error.bat" folder

    exit /b 1

)



if exist "patch-launch-env.cmd" (

    call "patch-launch-env.cmd" "%CD%"

) else (

    set "PYTHONPATH=%CD%"

)



if exist "%LOCALAPPDATA%\PeechaSync\pending-update.json" (
    if exist "%LOCALAPPDATA%\PeechaSync\update-apply-failed.json" (
        echo [%date% %time%] skip cached apply - recent failure>>"%LOG_FILE%"
    ) else if exist "peecha-apply-cached-update.ps1" (

        where powershell >nul 2>&1

        if not errorlevel 1 (

            powershell -NoProfile -ExecutionPolicy Bypass -File "peecha-apply-cached-update.ps1" -InstallRoot "%CD%." >>"%LOG_FILE%" 2>&1

        )

    )

)



if exist "peecha-version-refresh.cmd" (

    call "peecha-version-refresh.cmd" "%CD%." >>"%LOG_FILE%" 2>&1

) else if exist "peecha-version-refresh.ps1" (

    where powershell >nul 2>&1

    if not errorlevel 1 (

        powershell -NoProfile -ExecutionPolicy Bypass -File "peecha-version-refresh.ps1" -InstallRoot "%CD%." >>"%LOG_FILE%" 2>&1

    )

)



if exist ".peecha-pyc-only" (

    if not exist "main.pyc" (

        echo [%date% %time%] missing main.pyc >> "%LOG_FILE%"

        call "show-startup-error.bat" main

        exit /b 1

    )

) else if not exist "main.py" if not exist "main.pyc" (

    echo [%date% %time%] missing main >> "%LOG_FILE%"

    call "show-startup-error.bat" main

    exit /b 1

)



set "PY="

if exist "python\python.exe" set "PY=python\python.exe"

if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if not defined PY (

    echo [%date% %time%] missing python >> "%LOG_FILE%"

    call "show-startup-error.bat" venv

    exit /b 1

)



call "set-python-env.bat" "%CD%\%PY%" "%CD%"



REM با نسخه‌ی نصب‌شده کلید می‌شه، نه یک‌بار برای همیشه — بعدِ هر
REM آپدیت، VERSION.txt عوض می‌شه و تست‌های سنگینِ زیر یک‌بار دیگه
REM (و فقط یک‌بار) اجرا می‌شن، نه هر بار که کاربر برنامه رو باز می‌کنه.
REM هر کدوم از این سه مرحله (self-test importها، verify-main-pyc.ps1،
REM test-bootstrap.ps1) خودش یک پردازشِ کاملِ پایتون/PyQt5 رو دوباره
REM import می‌کنه — یعنی قبل از اجرایِ واقعی، PyQt5 تا سه بار جدا از هم
REM لود می‌شد؛ همینه که «بازشدنِ برنامه کند»ه.
set "VERIFIED_FILE=%LOCALAPPDATA%\PeechaSync\verified-launch.txt"
set "CUR_VER="
if exist "%ROOT%VERSION.txt" set /p CUR_VER=<"%ROOT%VERSION.txt"
set "LAST_VERIFIED="
if exist "%VERIFIED_FILE%" set /p LAST_VERIFIED=<"%VERIFIED_FILE%"

if defined CUR_VER if "%CUR_VER%"=="%LAST_VERIFIED%" (

    echo [%date% %time%] skip heavy verify - already verified v%CUR_VER% >> "%LOG_FILE%"

    goto :after_verify

)



set "IMPORT_LOG=%TEMP%\peecha-import-test.txt"

"%CD%\%PY%" -c "import PyQt5, pyodbc, requests, woocommerce, cryptography, psutil; print('OK all imports')" >"%IMPORT_LOG%" 2>&1

if errorlevel 1 (

    type "%IMPORT_LOG%" >> "%LOG_FILE%" 2>nul

    echo [%date% %time%] import failed >> "%LOG_FILE%"

    call "show-startup-error.bat" venv

    exit /b 1

)



if exist "main.pyc" (

    set "BOOT_RC=0"

    if exist "verify-main-pyc.ps1" (

        where powershell >nul 2>&1

        if not errorlevel 1 (

            powershell -NoProfile -ExecutionPolicy Bypass -File "verify-main-pyc.ps1" -PythonExe "%CD%\%PY%" -MainPyc "%CD%\main.pyc" -InstallDir "%CD%" -TimeoutSec 15

            set "BOOT_RC=!ERRORLEVEL!"

            if not "!BOOT_RC!"=="0" (

                type "%TEMP%\peecha-main-pyc-test.txt" >> "%LOG_FILE%" 2>nul

            )

        )

    )

    if not "!BOOT_RC!"=="0" (

        "%CD%\%PY%" -c "import marshal; f=open('main.pyc','rb'); f.read(16); marshal.loads(f.read())" 2>>"%LOG_FILE%"

        if errorlevel 1 (

            echo [%date% %time%] main.pyc bad magic - run Install PeechaSync.bat option 1 >> "%LOG_FILE%"

            call "show-startup-error.bat" launch

            exit /b 1

        )

        if exist "test-bootstrap.ps1" (

            where powershell >nul 2>&1

            if not errorlevel 1 (

                powershell -NoProfile -ExecutionPolicy Bypass -File "test-bootstrap.ps1" -PythonExe "%CD%\%PY%" -InstallDir "%CD%" -TimeoutSec 20

                set "BOOT_RC=!ERRORLEVEL!"

                if not "!BOOT_RC!"=="0" type "%TEMP%\peecha-bootstrap-test.txt" >> "%LOG_FILE%" 2>nul

            )

        )

        if not "!BOOT_RC!"=="0" (

            echo [%date% %time%] bootstrap failed - run Install PeechaSync.bat option 1 >> "%LOG_FILE%"

            call "show-startup-error.bat" launch

            exit /b 1

        )

    )

)



if defined CUR_VER (

    > "%VERIFIED_FILE%" echo %CUR_VER%

)



:after_verify

echo [%date% %time%] using %CD%\%PY% >> "%LOG_FILE%"

set "PYGUI="
if exist "python\pythonw.exe" set "PYGUI=python\pythonw.exe"
if not defined PYGUI set "PYGUI=%PY%"

call :LaunchGui

set "LAUNCH_RC=%ERRORLEVEL%"

if not "%LAUNCH_RC%"=="0" (

    echo [%date% %time%] launch-gui failed rc=%LAUNCH_RC% - retry after env repair >> "%LOG_FILE%"

    if exist "repair-launch-env.cmd" call "repair-launch-env.cmd" "%CD%"

    if exist "patch-launch-env.cmd" call "patch-launch-env.cmd" "%CD%"

    call :LaunchGui

    set "LAUNCH_RC=%ERRORLEVEL%"

)

if not "%LAUNCH_RC%"=="0" (

    echo [%date% %time%] launch-gui failed rc=%LAUNCH_RC% >> "%LOG_FILE%"

    call "show-startup-error.bat" launch

    exit /b 1

)

echo [%date% %time%] launched >> "%LOG_FILE%"

exit /b 0



:LaunchGui

if exist "launch-gui.ps1" (

    where powershell >nul 2>&1

    if not errorlevel 1 (

        powershell -NoProfile -ExecutionPolicy Bypass -File "launch-gui.ps1" -LogFile "%LOG_FILE%"

        exit /b %ERRORLEVEL%

    )

)

if exist "launch-gui.cmd" (

    call "launch-gui.cmd" "%LOG_FILE%" "%PYGUI%"

    exit /b %ERRORLEVEL%

)

echo [%date% %time%] no launcher >> "%LOG_FILE%"

exit /b 5

