@echo off
REM One-click AI Pulse for Windows: double-click this file.
REM First run creates the virtual environment; every run opens the site when done.
cd /d "%~dp0"
title AI Pulse

if not exist ".venv\Scripts\python.exe" (
    echo First run: setting up Python environment, this takes a minute...
    python -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :fail
)

".venv\Scripts\python.exe" -m ai_pulse --open %*
if errorlevel 1 goto :fail
REM Close by itself a few seconds after the browser opens.
ping -n 5 127.0.0.1 >nul
exit /b 0

:fail
echo.
echo Something went wrong - read the messages above.
pause
exit /b 1
