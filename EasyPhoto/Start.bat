@echo off
setlocal
chcp 65001 >nul
color 0A
title EasyPhoto - Photo Studio
cd /d "%~dp0"
echo.
echo   ====================================================
echo                         easyphoto
echo                 Your local photo studio
echo   ====================================================
echo.
echo   Opening your workshop. Python and models stay local.
echo.
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1"
if errorlevel 1 (
  echo.
  echo EasyPhoto could not start. See the error above.
  pause
)
