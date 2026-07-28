@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-and-fix-after-power-outage.ps1" %*
exit /b %ERRORLEVEL%
