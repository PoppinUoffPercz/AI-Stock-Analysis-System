from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest_engine import cli


def _csv(path: Path) -> None:
    path.write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2024-01-03,11,13,10,12,200\n"
        "2024-01-02,10,12,9,11,100\n"
        "2024-01-04,12,14,11,13,300\n",
        encoding="utf-8",
    )


def test_cli_ingest_csv_writes_clean_data_readable_by_cli(tmp_path, capsys):
    source = tmp_path / "bars.csv"
    _csv(source)

    rc = cli.main(
        [
            "ingest",
            "--source",
            "csv",
            "--input",
            str(source),
            "--symbol",
            "test",
            "--start",
            "2024-01-03",
            "--end",
            "2024-01-04",
            "--data-root",
            str(tmp_path / "market-data"),
        ]
    )

    assert rc == 0
    assert "Ingested 2 rows for TEST" in capsys.readouterr().out
    clean = cli._clean_ohlc("TEST", data_root=tmp_path / "market-data", start=None, end=None)
    assert clean.index.tolist() == list(pd.to_datetime(["2024-01-03", "2024-01-04"], utc=True))
    assert clean["close"].tolist() == [12.0, 13.0]
    assert (tmp_path / "market-data" / "universe" / "TEST_boundary.csv").exists()


def test_cli_ingest_rejects_malformed_csv_without_writing(tmp_path, capsys):
    source = tmp_path / "bad.csv"
    source.write_text("Date,Open,High,Low,Volume\n2024-01-02,10,12,9,100\n")

    rc = cli.main(
        [
            "ingest",
            "--source",
            "csv",
            "--input",
            str(source),
            "--symbol",
            "TEST",
            "--destination",
            str(tmp_path / "destination"),
        ]
    )

    assert rc == 1
    assert "missing required columns" in capsys.readouterr().err
    assert not (tmp_path / "destination" / "clean").exists()
