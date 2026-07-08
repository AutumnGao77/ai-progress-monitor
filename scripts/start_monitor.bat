@echo off
cd /d "%~dp0\.."
set "LOG_DIR=%LOCALAPPDATA%\AI Progress Monitor"
if "%LOCALAPPDATA%"=="" set "LOG_DIR=%CD%\logs"
set "LOG_FILE=%LOG_DIR%\monitor.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
echo.>> "%LOG_FILE%"
echo [%DATE% %TIME%] Starting AI Progress Monitor>> "%LOG_FILE%"
set PYTHON_CMD=
set PYTHON_ARGS=
where py >nul 2>nul
if not errorlevel 1 (
  set PYTHON_CMD=py
  set PYTHON_ARGS=-3
) else (
  where python3 >nul 2>nul
  if not errorlevel 1 (
    set PYTHON_CMD=python3
    set PYTHON_ARGS=
  ) else (
    where python >nul 2>nul
    if not errorlevel 1 (
      set PYTHON_CMD=python
      set PYTHON_ARGS=
    )
  )
)
if "%PYTHON_CMD%"=="" (
  echo Python 3 was not found. Install Python 3 and try again.
  echo Python 3 was not found. Install Python 3 and try again.>> "%LOG_FILE%"
  pause
  exit /b 1
)
%PYTHON_CMD% %PYTHON_ARGS% ai-progress-monitor.pyz --open %* >> "%LOG_FILE%" 2>&1
if errorlevel 130 (
  echo Monitor stopped.
  exit /b 130
)
if errorlevel 1 (
  echo Monitor failed. See log: "%LOG_FILE%"
  type "%LOG_FILE%"
  pause
  exit /b 1
)
