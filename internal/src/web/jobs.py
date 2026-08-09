"""BackgroundJob — a small thread-safe state holder for long-running tasks.

Architecture review §4: the pipeline run and the model download each hand-rolled
the *same* pattern — a module-level ``dict`` + ``threading.Lock`` + capped log
list + started/finished/running/ok bookkeeping + a JSON snapshot. Adding a third
long task meant copy-pasting it again. This unifies that pattern so both callers
share one implementation and a fourth task is a few lines.

Design goals:
- **Behaviour-identical**: the JSON snapshot must reproduce the exact keys both
  endpoints returned before, so the frontend and API tests keep passing.
- **Thread-safe**: every field mutation and the snapshot go through one lock.
- **Extensible**: task-specific fields (qq/steps/stopped_at, name/error) live in
  a free-form ``extra`` dict that is flattened into the snapshot.

Note: this does not add cancellation — Python threads can't be safely force
killed and the underlying work (ModelScope download / pipeline) exposes no
cancel hook (see review PR #28). It only unifies status/logs bookkeeping.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

MAX_LOGS = 500


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class BackgroundJob:
    """Thread-safe status/log holder for a single long-running background task.

    A single instance represents one *slot* (e.g. "the pipeline", "the download")
    that runs at most one task at a time — matching the previous single-dict
    behaviour. Concurrency guard is the caller's responsibility via ``running``.
    """

    def __init__(self, extra_defaults: Optional[Dict[str, Any]] = None) -> None:
        self._lock = threading.Lock()
        self._max_logs = MAX_LOGS
        # Common lifecycle fields (shared by every long task).
        self.running: bool = False
        self.ok: Optional[bool] = None
        self.logs: List[str] = []
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        # Task-specific fields, flattened into the snapshot. Defaults define the
        # keys that always appear (so the JSON shape is stable even when idle).
        self._extra_defaults: Dict[str, Any] = dict(extra_defaults or {})
        self.extra: Dict[str, Any] = dict(self._extra_defaults)

    @property
    def lock(self) -> threading.Lock:
        """Expose the lock so callers can guard check-then-start atomically."""
        return self._lock

    # ---- lifecycle -------------------------------------------------------
    def start(self, **extra: Any) -> None:
        """Mark the job running and reset lifecycle + extra fields.

        Call inside ``with job.lock:`` when you need an atomic
        check-``running``-then-``start`` (the previous code did exactly this).
        """
        with self._lock:
            self.running = True
            self.ok = None
            self.logs = []
            self.started_at = _now()
            self.finished_at = None
            self.extra = dict(self._extra_defaults)
            self.extra.update(extra)

    def log(self, message: str) -> None:
        """Append a log line (capped at MAX_LOGS, thread-safe)."""
        with self._lock:
            self.logs.append(message)
            del self.logs[:-self._max_logs]

    def set_extra(self, **fields: Any) -> None:
        """Update task-specific fields thread-safely (e.g. ok/error/steps)."""
        with self._lock:
            self.extra.update(fields)

    def update_extra_locked(self, **fields: Any) -> None:
        """Like set_extra but assumes the caller already holds ``lock``."""
        self.extra.update(fields)

    def finish(self, ok: Optional[bool] = None, **extra: Any) -> None:
        """Mark the job finished (not running) and stamp finished_at."""
        with self._lock:
            self.running = False
            if ok is not None:
                self.ok = ok
            self.extra.update(extra)
            self.finished_at = _now()

    # ---- read ------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        """Thread-safe snapshot: common fields + flattened extra fields.

        Extra fields override common ones on key collision (there are none in
        practice); this reproduces the exact dict both endpoints returned.
        """
        with self._lock:
            snap: Dict[str, Any] = {
                "running": self.running,
                "ok": self.ok,
                "logs": list(self.logs),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }
            snap.update(self.extra)
            return snap
