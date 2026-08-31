"""
WhatsApp Notification Bridge for the Scion-Bot Trading Agent.

Sends structured trading alerts to a configured WhatsApp chat via the
zappy-mcp MCP server (http://localhost:4096 or configured port).

Usage:
  1. As a Python module: `from notify import ScionNotifier` and call .send_alert()
  2. As a CLI: `python notify.py "message text"`

The bridge communicates with the zappy-mcp WebSocket MCP server to send messages.
It uses the MCP stdio protocol by spawning the zappy-mcp node process.
"""
import json
import os
import subprocess
import sys
import asyncio
import websockets


ZAPPY_MCP_PATH = os.environ.get(
    "ZAPPY_MCP_PATH",
    os.path.join(os.path.expanduser("~"), "zappy-mcp", "src", "index.js")
)
ZAPPY_CONFIG_PATH = os.environ.get(
    "ZAPPY_CONFIG_PATH",
    os.path.join(os.path.expanduser("~"), "zappy-mcp", ".zappy-mcp.json")
)
# Alternatively, talk to the MCP HTTP bridge if zappy-mcp is already running
MCP_HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "0"))


class ScionNotifier:
    """
    Sends WhatsApp trading alerts via the zappy-mcp server.
    Supports two modes:
      1. HTTP bridge (if zappy-mcp is running with --port)
      2. stdio spawn (launches zappy-mcp as a subprocess)
    """

    def __init__(self, recipient_id=None, config_path=None):
        self.recipient_id = recipient_id
        self.config_path = config_path or ZAPPY_CONFIG_PATH
        self.zappy_path = ZAPPY_MCP_PATH

    def _format_alert(self, title, body):
        """Format a clean WhatsApp-ready alert message."""
        separator = "*" * 40
        msg = f"{separator}\n*{title}*\n{separator}\n\n{body}"
        return msg

    async def send_via_websocket(self, message):
        """Send message via zappy-mcp's WebSocket interface (if running with --port)."""
        if MCP_HTTP_PORT == 0:
            return False

        uri = f"ws://localhost:{MCP_HTTP_PORT}"
        try:
            async with websockets.connect(uri) as ws:
                # MCP-style JSON-RPC call
                request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "send_message",
                        "arguments": {
                            "to": self.recipient_id,
                            "message": message
                        }
                    }
                }
                await ws.send(json.dumps(request))
                response = await ws.recv()
                print(f"[Notifier] WebSocket response: {response}")
                return True
        except Exception as e:
            print(f"[Notifier] WebSocket send failed: {e}")
            return False

    def send_via_stdio(self, message):
        """Send message by spawning zappy-mcp as a subprocess with MCP stdio protocol."""
        if not os.path.exists(self.zappy_path):
            print(f"[Notifier] zappy-mcp not found at {self.zappy_path}")
            print("[Notifier] Skipping WhatsApp notification.")
            return False

        try:
            # Build MCP initialize + tool call sequence
            init_msg = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "scion-bot", "version": "1.0.0"}
                }
            }

            send_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "send_message",
                    "arguments": {
                        "to": self.recipient_id,
                        "message": message
                    }
                }
            }

            # Spawn the zappy-mcp process with stdio
            cmd = ["node", self.zappy_path, "--config", self.config_path]
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )

            # Send initialize
            proc.stdin.write(json.dumps(init_msg) + "\n")
            proc.stdin.flush()

            # Wait briefly for init response
            import time
            time.sleep(2)

            # Read available output (init response)
            proc.stdout.readline()

            # Send the message
            proc.stdin.write(json.dumps(send_msg) + "\n")
            proc.stdin.flush()

            # Wait for response
            time.sleep(3)
            proc.stdin.close()
            proc.terminate()

            print(f"[Notifier] Message sent via zappy-mcp stdio to {self.recipient_id}")
            return True

        except Exception as e:
            print(f"[Notifier] stdio send failed: {e}")
            return False

    def send_alert(self, title, body):
        """Send a formatted trading alert to WhatsApp."""
        message = self._format_alert(title, body)

        print(f"\n[ScionNotifier] Alert: {title}")
        print(message)

        # Try WebSocket first, fall back to stdio
        if MCP_HTTP_PORT != 0:
            success = asyncio.run(self.send_via_websocket(message))
            if success:
                return True

        # Fall back to stdio (only if recipient is configured)
        if self.recipient_id:
            return self.send_via_stdio(message)

        print("[Notifier] No recipient configured. Alert printed to console only.")
        return True  # Return True so the pipeline doesn't break without WhatsApp


def format_screener_alert(results_df, top_n=5):
    """Format screener results into a WhatsApp-ready alert."""
    if results_df.empty:
        return None

    lines = []
    lines.append("TOP SCION SCREENER CANDIDATES")
    lines.append(f"Generated: {os.popen('date /t').read().strip()}\n")

    for _, row in results_df.head(top_n).iterrows():
        lines.append(f"[{row['Symbol']}] Score: {row['Scion Score']}/100")
        lines.append(f"  Price: ${row['Price']} | Dist from Low: {row['Dist from Low']}")
        lines.append(f"  CR: {row['Current Ratio']} | D/E: {row['Debt/Equity']} | FCF: {row['FCF Yield']}")
        lines.append(f"  Sentiment: {row['Sentiment']} ({row['Sentiment Score']})")
        lines.append(f"  Reasons: {row['Reasons']}")
        lines.append("")

    return "\n".join(lines)


def format_analysis_alert(symbol, report_summary):
    """Format a deep-dive analysis summary into a WhatsApp alert."""
    lines = []
    lines.append(f"*SCION DEEP-DIVE: {symbol}*\n")
    lines.append(report_summary)
    return "\n".join(lines)


def format_portfolio_alert(portfolio_summary):
    """Format the portfolio summary for a daily WhatsApp update."""
    lines = []
    lines.append("*SCION PORTFOLIO DAILY UPDATE*\n")
    lines.append(portfolio_summary)
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        notifier = ScionNotifier()
        notifier.send_alert("Manual Scion-Bot Message", " ".join(sys.argv[1:]))
    else:
        print('Usage: python notify.py "message text"')
