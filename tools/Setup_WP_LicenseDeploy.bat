@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM One-time FTP config for plugin deploy
REM یک بار: یوزر/رمز FTP را در json پر کنید
set "CFG=%~dp0wp-license-deploy.local.json"
set "EX=%~dp0wp-license-deploy.local.json.example"

if not exist "%EX%" (
  echo Missing: wp-license-deploy.local.json.example
  pause
  exit /b 1
)

if not exist "%CFG%" (
  copy /Y "%EX%" "%CFG%" >nul
  echo Created: wp-license-deploy.local.json
  echo ساخته شد: wp-license-deploy.local.json
) else (
  echo Editing existing config...
  echo ویرایش همان فایل...
)

echo.
echo Fill in DirectAdmin -^> FTP Accounts -^> user + password, then Save.
echo ftpUser / ftpPassword را از پنل نت افزار پر کنید و Save.
echo remotePluginDir: if upload fails try wp-content/plugins/peecha-license-manager
echo useFtps: true if curl still fails after fixing user/password
echo.
notepad "%CFG%"
echo.
echo After save, run ONE command for every new version:
echo   tools\Run_Release_All.bat
echo   (build + git + GitHub release + FTP mirror)
echo.
echo Or step by step:
echo   Double-click Run_Deploy_WP_LicensePlugin.bat in this tools folder
echo   OR from project root:  tools\Run_Deploy_WP_LicensePlugin.bat
echo   OR if you are already in tools:  Run_Deploy_WP_LicensePlugin.bat
echo   (do NOT type tools\ when prompt ends with \tools)
echo.
echo بعد از Save یکی از اینها:
echo   از Explorer روی Run_Deploy_WP_LicensePlugin.bat دوبار کلیک
echo   یا از ریشه پروژه: tools\Run_Deploy_WP_LicensePlugin.bat
echo   یا اگر داخل tools هستید: Run_Deploy_WP_LicensePlugin.bat
pause
