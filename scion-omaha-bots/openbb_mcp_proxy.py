"""
OpenBB MCP stdio-to-HTTP proxy.
opencode launches this as a local stdio MCP server; it forwards requests
to the OpenBB MCP HTTP server running on 127.0.0.1:8001.

opencode config:
  "openbb": {
    "type": "local",
    "command": ["python", "C:\\Users\\alexp\\scion-bot\\openbb_mcp_proxy.py"]
  }

This script:
1. Starts the OpenBB MCP HTTP server as a subprocess (port 8001)
2. Waits for it to be ready
3. Reads JSON-RPC messages from stdin, forwards them as HTTP POST to the server
4. Writes SSE-parsed JSON-RPC responses back to stdout
"""

import sys
import json
import time
import subprocess
import threading
import httpx
import os

OPENBB_MCP_EXE = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Packages",
    "PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0",
    "LocalCache",
    "local-packages",
    "Python313",
    "Scripts",
    "openbb-mcp.exe",
)

MCP_URL = "http://127.0.0.1:8001/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_server_proc = None


def start_http_server():
    global _server_proc
    psi = subprocess.Popen(
        [OPENBB_MCP_EXE, "--host", "127.0.0.1", "--port", "8001",
         "--default-categories", "equity,news", "--tool-discovery"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _server_proc = psi

    # Wait for server to be ready (up to 30 seconds)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            r = httpx.post(MCP_URL,
                           content=json.dumps({"jsonrpc": "2.0", "id": 0,
                                               "method": "initialize",
                                               "params": {"protocolVersion": "2024-11-05",
                                                          "capabilities": {},
                                                          "clientInfo": {"name": "proxy", "version": "1.0"}}}),
                           headers=HEADERS, timeout=3)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)

    raise RuntimeError("OpenBB MCP HTTP server failed to start within 30s")


def forward_request(req_json: str) -> str:
    try:
        r = httpx.post(MCP_URL, content=req_json, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            error = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603,
                     "message": f"HTTP {r.status_code}: {r.text[:200]}"}}
            return json.dumps(error)

        # Parse SSE — extract the data: line
        for line in r.text.split("\n"):
            s = line.strip()
            if s.startswith("data:"):
                return s[5:].strip()
        return ""
    except Exception as e:
        error = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603,
                 "message": f"Proxy error: {e}"}}
        return json.dumps(error)


def main():
    start_http_server()

    # Send the initialize response we already captured during startup
    # (the start_http_server() already sent initialize and got 200)
    # We need to re-send what comes from stdin

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        response = forward_request(line)
        if response:
            sys.stdout.write(response + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    finally:
        if _server_proc:
            _server_proc.kill()