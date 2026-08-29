---
title: "WhatsApp Alerts"
date: 2026-07-07
tags:
  - docs
  - notifications
---

# WhatsApp Alerts

Both agents can send WhatsApp notifications via the `zappy-mcp` bridge.

## Setup

Configure `zappy-mcp` separately (not part of this codebase). The chat ID for your recipient must be configured via the MCP.

## Usage

```bash
# Scion-Bot with notification
python main.py --notify --recipient "CHAT_ID" run

# Omaha-Bot with notification
python buffett_main.py --notify --recipient "CHAT_ID" run

# Premarket with notification (Scion only currently)
python main.py --notify --recipient "CHAT_ID" premarket
```

## Recipient Configuration

The allowed recipient list is managed in the WhatsApp MCP configuration, not in the Python code.

## What Gets Sent

| Event | Agent | Content |
| :--- | :--- | :--- |
| News alert (thesis-breaking) | Scion | Symbol, headline, action required |
| News alert (panic buying opp) | Scion | Symbol, headline, capitulation signal |
| News alert (reversal catalyst) | Scion | Symbol, headline, buy trigger |
| Premarket briefing | Scion | SPY, VIX, candidate count |
| Run complete | Both | Summary with key findings |

## Notification Flow

```
news_engine.generate_alert_text()
  → formatted markdown string
  → notify.send_alert()
  → zappy-mcp
  → WhatsApp
```

## Troubleshooting

- If alerts don't send: check `notify.py` isn't swallowing errors
- Chat ID can be found via the WhatsApp MCP's `list_chats` tool
- The `--notify` flag is optional — everything works without it
