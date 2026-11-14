@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" setup.py
) else (
  py -3.12 setup.py
)
if errorlevel 1 (
  echo Setup failed. Make sure Python 3.12, Git, and FFmpeg are installed.
  exit /b 1
)
