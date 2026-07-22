@echo off
setlocal

set "APP_DIR=%~dp0"
set "PYTHON=C:\Users\8bits\miniconda3\pythonw.exe"

if not exist "%PYTHON%" set "PYTHON=C:\Users\8bits\miniconda3\python.exe"

start "Python Job Scheduler" "%PYTHON%" "%APP_DIR%app.py"

endlocal
