@echo off
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
python screener.py >> "%~dp0logs\screener_run.log" 2>&1
