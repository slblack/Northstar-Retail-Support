@echo off
rem Double-click to start Northstar Retail Support (runs start.ps1 next to this file).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
echo.
pause
