import csv, datetime
rows = list(csv.DictReader(open("trades.csv", encoding="utf-8")))
hdr = f"{'sym':<6}{'entry':>9}{'exit':>9}{'logged_pnl':>11}{'computed_pnl':>13}{'entry_date':<12}{'exit_date':<12}{'days_held':>10}"
print(hdr)
for r in rows:
    e = float(r["entry_price"])
    x = float(r["exit_price"])
    comp = (x - e) / e * 100
    ep = datetime.date.fromisoformat(r["entry_date"])
    xp = datetime.date.fromisoformat(r["exit_date"])
    days = (xp - ep).days
    print(f"{r['ticker']:<6}{e:>9.2f}{x:>9.2f}{r['pnl_pct']:>11}{comp:>13.2f}{r['entry_date']:<12}{r['exit_date']:<12}{days:>10}")
