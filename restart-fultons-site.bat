@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\restart-fultons-home-server.ps1" %*
exit /b %ERRORLEVEL%
