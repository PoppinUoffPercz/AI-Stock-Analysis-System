import httpx, json, time, sys

url = "http://127.0.0.1:8001/mcp"
body = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
               "clientInfo": {"name": "bridge", "version": "1.0"}}})
headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

for i in range(20):
    try:
        r = httpx.post(url, content=body, headers=headers, timeout=3)
        if r.status_code == 200:
            sys.exit(0)
    except Exception:
        pass
    import time
    time.sleep(1)

sys.exit(1)