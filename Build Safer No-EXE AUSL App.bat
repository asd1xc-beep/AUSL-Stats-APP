@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build Safer No-EXE AUSL App.ps1"
if errorlevel 1 (
  echo AUSL safer no-EXE build failed.
  pause
  exit /b 1
)
