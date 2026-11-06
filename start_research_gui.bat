@echo off
setlocal
rem Prefer this checkout's environment; otherwise use the current user's Python.
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" gui\research_gui.py
    exit /b
)
if exist "%USERPROFILE%\anaconda3\pythonw.exe" (
    start "" "%USERPROFILE%\anaconda3\pythonw.exe" gui\research_gui.py
    exit /b
)
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pythonw.exe gui\research_gui.py
    exit /b
)
echo Python was not found. Install Python and the dependencies in the README.
pause
exit /b 1
