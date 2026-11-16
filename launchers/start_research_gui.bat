@echo off
setlocal
rem The runtime location is selected and recorded by Setup.bat on this PC.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_windows.ps1"
if errorlevel 1 pause
