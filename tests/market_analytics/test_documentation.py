from pathlib import Path


def test_methodology_documents_required_distinctions():
    text = Path("docs/methodology/market-analytics-methodology.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "public option OI does not disclose dealer inventory",
        "flow delta is not dealer DEX",
        "flow delta exhaustion is not dealer hedge saturation",
        "TPO POC counts time-price occurrences",
        "volume POC counts traded volume",
        "candle-derived volume profile is approximate",
    ):
        assert phrase in text
