from __future__ import annotations

import json

import pytest

from stock_analysis import cli


def test_checkpoint_cli_emits_machine_readable_summary(tmp_path, capsys):
    code = cli.main(
        [
            "--outputs-root",
            str(tmp_path),
            "intelligence",
            "checkpoint",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "research_fixture"
    assert payload["regime"]
    assert "candidate_count" in payload
    assert payload["artifacts"]["analytics"].endswith(".json")


def test_intelligence_help_does_not_require_network(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["intelligence", "--help"])

    assert error.value.code == 0
    assert "checkpoint" in capsys.readouterr().out
