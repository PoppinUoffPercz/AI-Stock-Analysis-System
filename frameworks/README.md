# Analysis Frameworks

These files are the definitions that shape how the agents perform research. They are intentionally separated from generated ticker reports and runtime state.

- `agents/` — Burry/Scion and Buffett/Omaha agent profiles plus the council prompt.
- `prompts/` — reusable research prompts and analyst workflow prompts.
- `methodologies/` — Burry, Buffett, contrarian, and value-investing methodologies.
- `risk/` — risk management, position sizing, technical patterns, sentiment, options, and short-interest rules.
- `data/` — financial data sources, economic indicators, and the financial research database.
- `skills/` — model-facing operating instructions; the credit-monitor skill is the current included skill.

The Python files in `scion-omaha-bots/` remain the executable implementation. These Markdown files are the human/model-readable framework layer that explains the decisions and operating rules.
