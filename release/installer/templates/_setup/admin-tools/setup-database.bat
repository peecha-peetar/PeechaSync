@echo off
chcp 65001 >nul 2>&1
call "%~dp0..\_lib\paths.bat"
call "%~dp0..\_lib\ensure-sql-express.bat"

cls
echo ========================================
echo PeechaSync - SQL Database Setup
echo نصب / راه‌اندازی دیتابیس SQL
echo ========================================
echo.
echo EN
echo 1. SQL Express service is checked/started automatically when possible.
echo 2. Copy your Dejavu MDF file to a local folder.
echo 3. Run PeechaSync - Settings - DB is pre-filled from saved config.
echo 4. Use Test SQL Connection if needed (auto-fixes Server name).
echo.
echo FA
echo 1. سرویس SQL Express در صورت امکان خودکار بررسی/روشن می‌شود.
echo 2. فایل MDF را در یک پوشه محلی کپی کنید.
echo 3. برنامه را اجرا کنید - تب تنظیمات - نام DB از قبل پر است.
echo 4. در صورت نیاز «تست اتصال SQL» (Server خودکار اصلاح می‌شود).
echo.
echo Typical instance: .\SQLEXPRESS or localhost\SQLEXPRESS
echo Staging folder: C:\ProgramData\PeechaSync\databases\
echo.
set /p OPEN=Open SQL staging folder? (y/n) / باز کردن پوشه staging؟: 
if /i "%OPEN%"=="y" (
    if not exist "C:\ProgramData\PeechaSync\databases" mkdir "C:\ProgramData\PeechaSync\databases"
    start "" "C:\ProgramData\PeechaSync\databases"
)
echo.
pause
exit /b 0
