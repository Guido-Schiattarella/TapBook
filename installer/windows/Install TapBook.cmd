@echo off
rem TapBook: installation on Windows. Right-click this file and choose "Run as administrator".
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
echo Press any key to close this window.
pause >nul
