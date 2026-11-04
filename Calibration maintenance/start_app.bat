@echo off
setlocal
rem Prefer this checkout's environment; otherwise use the current user's Python.
cd /d "%~dp0code"
if exist "%~dp0..\.venv\Scripts\pythonw.exe" (
    start "" "%~dp0..\.venv\Scripts\pythonw.exe" app.py
    exit /b
)
if exist "%USERPROFILE%\anaconda3\pythonw.exe" (
    start "" "%USERPROFILE%\anaconda3\pythonw.exe" app.py
    exit /b
)
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pythonw.exe app.py
    exit /b
)
echo Python was not found. Install Python and the dependencies in the README.
pause
exit /b 1
