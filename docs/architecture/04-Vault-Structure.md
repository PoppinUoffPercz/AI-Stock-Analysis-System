---
title: "Vault Structure"
date: 2026-07-08
tags:
  - docs
  - vault
---

# Vault Structure

Every report from both agents lands in specific folders for easy cross-referencing.

```
Obsidian Vault/
│
├── Stock Research/
│   │
│   ├── Stock Analysis/          ← Deep-dives, top picks, pre-market briefs
│   │   ├── YYYY-MM-DD Pre-Market Brief.md         (both agents)
│   │   ├── YYYY-MM-DD Top Picks.md                (dual-agent consensus)
│   │   └── SYMBOL Analysis.md                     (individual ticker deep-dives)
│   │
│   ├── Daily Briefs/            ← Daily position checks
│   │   └── YYYY-MM-DD Position Check.md           (from daily_check.py)
│   │
│   ├── Debates/                 ← Bull/Bear/Judge debate reports
│   │   └── YYYY-MM-DD TICKER Debate.md            (from debate.py)
│   │
│   ├── Credit Monitor/          ← Credit market reports
│   │   ├── YYYY-MM-DD Credit Report.md            (daily snapshot)
│   │   └── Credit Cycle Tipping Point Analysis.md  (long-term thesis)
│   │
│   ├── Performance/             ← Performance reports + feedback recommendations
│   │   ├── YYYY-MM-DD Performance Report.md       (from report_card.py)
│   │   └── YYYY-MM-DD Feedback Report.md          (from feedback.py)
│   │
│   ├── News Outputs/            ← News synthesis
│   │   └── YYYY-MM-DD Market News Synthesis.md
│   │
│   ├── Methodologies/           ← Core trading methodologies
│   │   ├── Michael Burry Methodology.md
│   │   ├── Warren Buffett Methodology.md
│   │   ├── Contrarian Trading Framework.md
│   │   └── Value Investing Metrics.md
│   │
│   ├── Reference/               ← Reference knowledge base
│   │   ├── Swing Trading Technical Patterns.md
│   │   ├── Key Economic Indicators.md
│   │   ├── Market Sentiment Indicators.md
│   │   ├── Options and Short Interest for Contrarians.md
│   │   ├── Position Sizing Models.md
│   │   ├── Risk Management Ruleset.md
│   │   ├── Financial Data Sources and APIs.md
│   │   ├── Famous Contrarian Investors.md
│   │   └── Hedge Fund.md
│   │
│   ├── Ticker Reports/          ← Individual company analysis
│   │   └── SYMBOL — Senior Financial Analyst Report.md
│   │
│   ├── Agent Profiles/          ← Agent definitions and comparisons
│   │   ├── Scion Bot Agent Reference.md
│   │   ├── TradingAgents Comparison.md
│   │   └── Council Prompt.md
│   │
│   ├── Research Platform/       ← Research infrastructure
│   │   ├── Financial Research Database.md         (master coverage directory)
│   │   └── Stock Research Prompts.md              (research query templates)
│   │
│   ├── Operational/             ← Operation logs and watchlists
│   │   └── YYYY-MM-DD Market-Open Watchlist.md
│   │
│   └── _state/                  ← Automated state data (JSON/CSV)
│
├── Clippings/                   ← Web clippings / saved articles
│
├── copilot/                     ← Copilot AI chat history
│   └── copilot-conversations/
│
└── System Guide/                ← THIS FOLDER: documentation
    ├── 00-INDEX.md
    ├── 01-Dual-Agent-System.md
    ├── 02-CLI-Reference.md
    ├── 03-Credit-Monitor.md
    ├── 04-Vault-Structure.md
    ├── 05-Workflows.md
    ├── 06-File-Manifest.md
    ├── 07-WhatsApp-Alerts.md
    ├── 08-Full-Operating-Manual.md
    ├── 09-Performance-Tracker.md
    ├── 10-OpenBB-Integration.md
    └── 11-Debate-Engine.md
```

## File Naming Convention

- Dates: `YYYY-MM-DD` prefix (for natural sort)
- Agent origin: Not in filename — embedded in YAML frontmatter `tags:`
- Tags used: `premarket`, `daily-brief`, `credit`, `analysis`, `top-picks`, `debate`

## YAML Frontmatter

Every auto-generated file should include:

```yaml
---
title: "Descriptive Title"
date: 2026-07-08
tags:
  - relevant-tag
---
```

## Cross-Referencing

Use Obsidian wiki links (`...`) between related reports. The Research Platform/Financial Research Database.md acts as the master directory of all coverage.