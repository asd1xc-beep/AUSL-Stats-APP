@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build Shareable AUSL App.ps1"
if errorlevel 1 (
  echo AUSL shareable build failed.
  pause
  exit /b 1
)
