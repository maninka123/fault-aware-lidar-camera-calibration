@echo off
setlocal
cd /d "%~dp0"
rem Modern browser interface (opens http://127.0.0.1:8765).
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" tools\webui.py
) else (
    python tools\webui.py
)
