@echo off
cd /d "%~dp0\.."
set PYTHONPATH=src
python -m ai_progress_monitor --demo --no-windows --host 127.0.0.1 --port 8765
