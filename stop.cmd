@echo off
rem Double-click to stop Northstar Retail Support (runs stop.ps1 next to this file).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
echo.
pause
