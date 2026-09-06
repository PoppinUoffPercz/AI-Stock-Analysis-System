import multiprocessing
import time

from backtest_engine.experiment_index import ExperimentIndex
from backtest_engine.reproducibility import RunManifest


def _write_records(path, worker, ready):
    index = ExperimentIndex(path)
    original_read = index._read_unlocked

    def delayed_read():
        records = original_read()
        time.sleep(0.03)
        return records

    index._read_unlocked = delayed_read
    ready.wait(timeout=20)
    for number in range(10):
        run_id = "shared" if number == 0 else f"w{worker}-{number}"
        manifest = RunManifest.from_parts(
            stable={"engine": "fixture"}, provenance={"run_id": run_id}, identity_hash=run_id
        )
        index.append(manifest)


def test_spawned_writers_preserve_records_and_deduplicate(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready = context.Barrier(4)
    path = tmp_path / "experiments.jsonl"
    workers = [
        context.Process(target=_write_records, args=(path, number, ready)) for number in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        for worker in workers:
            worker.join(30)
            assert worker.exitcode == 0
        records = ExperimentIndex(path).filter()
        assert len(records) == 37
        assert {r["run_id"] for r in records} == {"shared"} | {
            f"w{w}-{n}" for w in range(4) for n in range(1, 10)
        }
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join()
