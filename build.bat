@echo off
REM Build a standalone Windows executable with PyInstaller.
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install pyinstaller
".venv\Scripts\python.exe" -m PyInstaller build.spec --noconfirm
echo.
echo Build complete: dist\DynamicLoadTest\DynamicLoadTest.exe
