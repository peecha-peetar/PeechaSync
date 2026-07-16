@echo off
setlocal EnableExtensions
set "OUT_VAR=%~1"
if "%OUT_VAR%"=="" set "OUT_VAR=INSTALL_DIR"
set "FALLBACK=%~2"
if "%FALLBACK%"=="" set "FALLBACK=C:\PeechaSync"

set "RESULT=%FALLBACK%"
if exist "%LOCALAPPDATA%\PeechaSync\install.loc" (
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$f=Join-Path $env:LOCALAPPDATA 'PeechaSync/install.loc'; if(Test-Path -LiteralPath $f){$x=(Get-Content -LiteralPath $f -Raw -Encoding UTF8).Trim().Trim([char]0xFEFF); if($x){$x}}"`) do (
        set "RESULT=%%P"
    )
)
if not exist "%RESULT%" set "RESULT=%FALLBACK%"
endlocal & set "%OUT_VAR%=%RESULT%"
