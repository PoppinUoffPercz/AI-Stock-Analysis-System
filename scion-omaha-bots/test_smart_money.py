from smart_money import _parse_insider_purchases, get_institutional_signal
import pandas as pd

rows = [
    {"Insider Purchases Last 6m": "Purchases", "Shares": 60},
    {"Insider Purchases Last 6m": "Sales", "Shares": 40},
    {"Insider Purchases Last 6m": "% Net Shares Purchased (sold)", "Shares": 0.5},
    {"Insider Purchases Last 6m": "Net Shares Purchased (Sold)", "Shares": 20, "Trans": 12},
]
net, buy_pct, trans = _parse_insider_purchases(rows)
assert net == 20, f"net={net}"
assert buy_pct == 0.6, f"buy_pct={buy_pct}"
assert trans == 12, f"trans={trans}"


class FakeTicker:
    institutional_holders = pd.DataFrame([
        {"Holder": "A", "pctChange": 0.05, "Shares": 10, "pctHeld": 0.01, "Value": 1},
        {"Holder": "B", "pctChange": -0.02, "Shares": 10, "pctHeld": 0.01, "Value": 1},
    ])
    mutualfund_holders = pd.DataFrame([
        {"Holder": "C", "pctChange": 0.10, "Shares": 10, "pctHeld": 0.01, "Value": 1},
    ])
    major_holders = pd.DataFrame(
        [[0.60], [0.66], [0.50], [1000]],
        index=["insidersPercentHeld", "institutionsPercentHeld",
               "institutionsFloatPercentHeld", "institutionsCount"],
    )


sig = get_institutional_signal("TEST", ticker=FakeTicker())
assert sig["institutions_pct"] == 50.0, sig["institutions_pct"]
assert abs(sig["avg_pct_change"] - (0.05 + -0.02 + 0.10) / 3 * 100) < 0.01, sig["avg_pct_change"]
assert sig["net_adding"] == 2, sig["net_adding"]
assert sig["net_reducing"] == 1, sig["net_reducing"]
print("test_smart_money OK")
