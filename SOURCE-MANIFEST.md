# Source Manifest

This repository is assembled from the live source projects and model-facing framework definitions. Treat tracked files as the authoritative inventory; do not maintain a hand-written file table here.

## Inclusion Policy

- `scion-omaha-bots/`: executable Python source, tests, requirements, and portable launchers from the local Scion-Bot source project.
- `backtest-engine/`: source, tests, notebooks, strategies, CI/configuration, and hypotheses from the local backtesting-engine source project.
- `frameworks/`: agent definitions and research framework notes from the bot project and Obsidian vault.
- `docs/architecture/`: directly related system guides and backtesting design notes from the Obsidian vault.

Canonical agent profiles live in `frameworks/agents/`; do not copy them into the executable bot directory.

## Exclusion Policy

- Generated ticker reports, screener outputs, daily briefs, debates, and news outputs.
- Portfolio/trade/reflection JSON and CSV state, logs, backups, downloaded data, caches, virtual environments, and editor configuration.
- Obsidian web clippings, mortgage co-pilot notes, voice/setup notes, and external OpenBB/WhatsApp credentials/configuration.

## Generate the Inventory

Run from the repository root:

```powershell
git ls-files
```

To include byte sizes without committing a stale snapshot:

```powershell
git ls-files | ForEach-Object { $item = Get-Item -LiteralPath $_; "{0}`t{1}" -f $item.Length, $_ }
```

When assembling a release, copy only files allowed by the policies above, then use `git status --short` and `git ls-files` to review additions and exclusions before committing.
