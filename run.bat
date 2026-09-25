@echo off
REM Launch the Dynamic Load Test desktop app from source.
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py %*
