import pandas as pd
from smart_money import _parse_insider_purchases, get_institutional_signal


def test_parse_insider_purchases_extracts_net_buy_share_and_transactions():
    rows = [
        {"Insider Purchases Last 6m": "Purchases", "Shares": 60},
        {"Insider Purchases Last 6m": "Sales", "Shares": 40},
        {"Insider Purchases Last 6m": "% Net Shares Purchased (sold)", "Shares": 0.5},
        {
            "Insider Purchases Last 6m": "Net Shares Purchased (Sold)",
            "Shares": 20,
            "Trans": 12,
        },
    ]

    net, buy_pct, transactions = _parse_insider_purchases(rows)

    assert net == 20
    assert buy_pct == 0.6
    assert transactions == 12


class FakeTicker:
    institutional_holders = pd.DataFrame(
        [
            {"Holder": "A", "pctChange": 0.05, "Shares": 10, "pctHeld": 0.01, "Value": 1},
            {"Holder": "B", "pctChange": -0.02, "Shares": 10, "pctHeld": 0.01, "Value": 1},
        ]
    )
    mutualfund_holders = pd.DataFrame(
        [
            {"Holder": "C", "pctChange": 0.10, "Shares": 10, "pctHeld": 0.01, "Value": 1},
        ]
    )
    major_holders = pd.DataFrame(
        [[0.60], [0.66], [0.50], [1000]],
        index=[
            "insidersPercentHeld",
            "institutionsPercentHeld",
            "institutionsFloatPercentHeld",
            "institutionsCount",
        ],
    )


def test_get_institutional_signal_summarizes_holder_changes():
    signal = get_institutional_signal("TEST", ticker=FakeTicker())

    assert signal["institutions_pct"] == 50.0
    assert abs(signal["avg_pct_change"] - (0.05 + -0.02 + 0.10) / 3 * 100) < 0.01
    assert signal["net_adding"] == 2
    assert signal["net_reducing"] == 1
