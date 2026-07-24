@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating AUSL virtual environment...
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Failed to create the Python 3.12 virtual environment.
    pause
    exit /b 1
  )
)

echo Installing AUSL app libraries...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt -c constraints.txt
if errorlevel 1 (
  echo Failed to install the pinned AUSL app libraries.
  pause
  exit /b 1
)

echo.
echo AUSL environment is ready.
echo You can now double-click "Launch AUSL Stats App.bat".
pause
