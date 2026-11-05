@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (start "" ".venv\Scripts\pythonw.exe" research_gui.py) else (start "" pythonw research_gui.py)
