@echo off
setlocal EnableExtensions
if not "%OS%"=="Windows_NT" exit /b 0

sc query "MSSQL$SQLEXPRESS" 2>nul | find /I "RUNNING" >nul
if not errorlevel 1 exit /b 0

sc query "MSSQL$SQLEXPRESS" 2>nul | find /I "STOPPED" >nul
if errorlevel 1 exit /b 0

echo SQL Express is stopped — trying to start...
echo SQL Express خاموش بود — در حال روشن کردن...
net start "MSSQL$SQLEXPRESS" >nul 2>&1
exit /b %ERRORLEVEL%
