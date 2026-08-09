"""Unit tests for the shared BackgroundJob abstraction (architecture review §4).

BackgroundJob unifies the pipeline-run and model-download status/log machinery.
Because both live endpoints now depend on it, these tests pin its contract
directly: snapshot shape, log capping, lifecycle transitions, and thread safety.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "internal" / "src" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from jobs import BackgroundJob, MAX_LOGS  # noqa: E402


def test_idle_snapshot_has_stable_shape():
    job = BackgroundJob(extra_defaults={"name": None, "error": None})
    snap = job.snapshot()
    assert snap == {
        "running": False, "ok": None, "logs": [],
        "started_at": None, "finished_at": None,
        "name": None, "error": None,
    }


def test_start_finish_lifecycle():
    job = BackgroundJob(extra_defaults={"name": None, "error": None})
    job.start(name="cosyvoice2")
    snap = job.snapshot()
    assert snap["running"] is True and snap["ok"] is None
    assert snap["name"] == "cosyvoice2" and snap["started_at"]
    job.set_extra(error="boom")
    job.finish(ok=False)
    snap = job.snapshot()
    assert snap["running"] is False and snap["ok"] is False
    assert snap["error"] == "boom" and snap["finished_at"]


def test_start_resets_previous_run():
    job = BackgroundJob(extra_defaults={"name": None})
    job.start(name="a")
    job.log("old")
    job.finish(ok=True)
    job.start(name="b")
    snap = job.snapshot()
    assert snap["logs"] == [] and snap["ok"] is None
    assert snap["name"] == "b" and snap["finished_at"] is None


def test_logs_are_capped():
    job = BackgroundJob()
    for i in range(MAX_LOGS + 50):
        job.log(f"line {i}")
    logs = job.snapshot()["logs"]
    assert len(logs) == MAX_LOGS
    assert logs[-1] == f"line {MAX_LOGS + 49}"  # newest kept


def test_concurrent_logging_is_thread_safe():
    job = BackgroundJob()
    job._max_logs = 10_000  # avoid cap dropping lines during the race
    n_threads, per = 8, 500

    def worker(tid: int):
        for i in range(per):
            job.log(f"{tid}:{i}")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(job.snapshot()["logs"]) == n_threads * per
