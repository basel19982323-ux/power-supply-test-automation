@echo off
REM One-time setup: create the virtualenv and install dependencies.
setlocal
cd /d "%~dp0"
python -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Setup complete. Launch the app with:  run.bat
