---
title: "System Index"
date: 2026-07-07
tags:
  - index
  - docs
---

# System Index

> Written as I hand over the keys. Everything you need to navigate what we built.

---

## Quick Links

| File | What |
| :--- | :--- |
| 01-Dual-Agent-System | Scion-Bot + Omaha-Bot overview |
| 02-CLI-Reference | Every command across both agents |
| 03-Credit-Monitor | Credit stress tracking tool |
| 04-Vault-Structure | Where everything lives in Obsidian |
| 05-Workflows | Daily/weekly routines |
| 06-File-Manifest | Every file in `scion-bot/` explained |
| 07-WhatsApp-Alerts | Notification setup |
| 08-Full-Operating-Manual | **Master guide** — everything in one doc |
| 09-Performance-Tracker | Trade logging, reports & feedback loop |
| 10-OpenBB-Integration | OpenBB MCP server — 20+ financial data providers |
| 11-Debate-Engine | Bull/Bear/Judge debate engine — subagent-driven score modifier |
| 12-Backtest-Engine | 3-phase backtesting framework — VBT → Backtrader → NautilusTrader |
| 13-Voice-Chat-Mode | Hands-free continuous voice conversation with the assistant (Piper TTS + Whisper) |

## TL;DR — The Two-Minute Tour

There are two Python trading agents in `./scion-omaha-bots\`:

| Agent | Style | Run Command |
| :--- | :--- | :--- |
| **Scion-Bot** (Burry) | Swing trade beaten-down stocks near 52W lows | `python main.py run` |
| **Omaha-Bot** (Buffett) | Buy quality compounders, hold forever | `python buffett_main.py run` |

Plus a **Credit Monitor** that tracks bond market stress:
```
python credit_monitor.py          # Full report
python credit_monitor.py --pulse  # One-liner for premarket
```

All three feed reports into this vault under `Stock Research/`.

Start with 01-Dual-Agent-System.
