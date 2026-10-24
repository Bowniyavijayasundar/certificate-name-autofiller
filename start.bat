@echo off
rem Double-click this file to install (first run) and start Certificate Name Autofiller.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
  echo.
  pause
)
