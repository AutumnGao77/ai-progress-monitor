@echo off
cd /d "%~dp0\.."
if "%AI_MONITOR_SESSION_ID%"=="" set AI_MONITOR_SESSION_ID=claude-code
if "%AI_MONITOR_TITLE%"=="" set AI_MONITOR_TITLE=Claude Code
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
  exit /b 1
)
%PYTHON_CMD% %PYTHON_ARGS% scripts\monitor_command.py --session-id "%AI_MONITOR_SESSION_ID%" --title "%AI_MONITOR_TITLE%" --tool claude_code -- %*
