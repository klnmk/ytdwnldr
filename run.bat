@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Run build.bat first, or open dist\ytdwnldr-portable\ytdwnldr.exe
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
endlocal
