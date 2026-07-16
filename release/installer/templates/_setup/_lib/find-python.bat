@echo off
set "PY_BOOT="
if defined ENGINE_PYTHON if exist "%ENGINE_PYTHON%" (
    set "PY_BOOT=%ENGINE_PYTHON%"
    goto :found
)
for %%P in (py -3.12 py -3.11 python) do (
    %%P -c "import sys; assert sys.version_info[:2]>=(3,11)" 2>nul && set "PY_BOOT=%%P" && goto :found
)
for %%X in (
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
) do (
    if exist %%X (
        %%X -c "import sys; assert sys.version_info[:2]>=(3,11)" 2>nul && set "PY_BOOT=%%X" && goto :found
    )
)
for %%K in (3.12 3.11) do (
    for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\Python\PythonCore\%%K\InstallPath" /ve 2^>nul') do (
        if exist "%%B\python.exe" (
            "%%B\python.exe" -c "import sys; assert sys.version_info[:2]>=(3,11)" 2>nul && set "PY_BOOT=%%B\python.exe" && goto :found
        )
    )
    for /f "tokens=2,*" %%A in ('reg query "HKCU\SOFTWARE\Python\PythonCore\%%K\InstallPath" /ve 2^>nul') do (
        if exist "%%B\python.exe" (
            "%%B\python.exe" -c "import sys; assert sys.version_info[:2]>=(3,11)" 2>nul && set "PY_BOOT=%%B\python.exe" && goto :found
        )
    )
)
exit /b 1
:found
exit /b 0
