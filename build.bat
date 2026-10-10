@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --cache-dir .tools-cache\pip -r requirements.lock.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe scripts\build.py
if errorlevel 1 exit /b 1
echo Done: dist\ytdwnldr-portable\ytdwnldr.exe
endlocal
