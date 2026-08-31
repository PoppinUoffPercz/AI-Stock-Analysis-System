from __future__ import annotations

from scripts.run_offline_demo import run_demo


def test_offline_demo_exercises_the_real_pipeline(tmp_path):
    report = run_demo(tmp_path)

    assert report["status"] == "PASS"
    assert report["checks"] == {
        "ingested_fixture": True,
        "point_in_time_universe": True,
        "strategy_and_signals": True,
        "exact_execution_costs": True,
        "benchmark": True,
        "persisted_result_and_manifest": True,
        "reload": True,
        "experiment_index": True,
        "compare": True,
        "offline_report": True,
    }
    assert report["fixture_rows"] == 80
    assert report["eligible_rows"] == 70
    assert report["runs"] == ["offline-zero", "offline-proportional"]
    assert report["comparison_rows"] == 2
