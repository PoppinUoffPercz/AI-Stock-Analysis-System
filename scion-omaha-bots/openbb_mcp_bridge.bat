@echo off
setlocal
cd /d "%~dp0"
start "OpenBB MCP" /B openbb-mcp --host 127.0.0.1 --port 8001 --default-categories equity,news --tool-discovery
python wait_for_openbb.py
