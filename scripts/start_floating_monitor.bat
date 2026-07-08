@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%SCRIPT_DIR%.."
set "POWERSHELL_SCRIPT=%ROOT_DIR%\native\windows\FloatingMonitor.ps1"
set "PYZ=%ROOT_DIR%\ai-progress-monitor.pyz"
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%POWERSHELL_SCRIPT%" -PyzPath "%PYZ%" %*
