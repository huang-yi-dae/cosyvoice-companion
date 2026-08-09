"""Background-task routes: automation pipeline + model catalog/download.

Extracted from app.py (architecture review §4). Both endpoint groups drive a
long-running background thread whose status is held in a BackgroundJob and
polled via a ``.../status`` endpoint, so they belong together.

``build_router(cfg)`` constructs the two single-slot BackgroundJob instances
and wires the handlers. Dependencies are passed in / imported lazily; this
module never imports app.py, keeping it import-cycle-free and unit-testable.
"""

from __future__ import annotations

import threading
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from jobs import BackgroundJob, _now as _jobs_now


class PipelineStart(BaseModel):
    qq: Optional[str] = None
    steps: Optional[List[str]] = None
    ptt_dir: Optional[str] = None
    continue_on_error: bool = False


class ModelDownload(BaseModel):
    name: str


def build_router(cfg) -> APIRouter:
    """Build the pipeline + models router bound to the given config."""
    from voicekit import pipeline as _pipeline  # lazy: avoid import at module load
    from voicekit import models as _models

    router = APIRouter(tags=["tasks"])

    # Single-slot jobs (unify the old *_lock/*_state module-level dicts).
    pipeline_job = BackgroundJob(
        extra_defaults={"qq": None, "steps": [], "stopped_at": None},
    )
    dl_job = BackgroundJob(extra_defaults={"name": None, "error": None})

    # ---- automation pipeline -------------------------------------------------
    def _pipeline_event(event: dict) -> None:
        """Update the pipeline job from a run_pipeline event (thread-safe)."""
        etype = event.get("type")
        if etype == "log":
            pipeline_job.log(event.get("message", ""))
        elif etype == "step":
            sid = event.get("id")
            with pipeline_job.lock:
                for s in pipeline_job.extra["steps"]:
                    if s["id"] == sid:
                        s["status"] = event.get("status", s["status"])
                        if event.get("error"):
                            s["error"] = event["error"]
                        break
        elif etype == "done":
            pipeline_job.finish(ok=event.get("ok"), stopped_at=event.get("stopped_at"))

    def _run_pipeline_bg(qq: str, step_ids, ptt_dir, stop_on_error) -> None:
        try:
            _pipeline.run_pipeline(
                cfg, qq=qq, step_ids=step_ids, on_event=_pipeline_event,
                ptt_dir=ptt_dir, stop_on_error=stop_on_error,
            )
        except Exception as e:  # noqa: BLE001 — record crash, never leave 'running' stuck
            _pipeline_event({"type": "log", "message": f"[fatal] {type(e).__name__}: {e}"})
            _pipeline_event({"type": "done", "ok": False, "stopped_at": None})

    @router.get("/api/pipeline/steps")
    async def api_pipeline_steps():
        return {"steps": _pipeline.pipeline_steps()}

    @router.post("/api/pipeline/start")
    async def api_pipeline_start(body: PipelineStart):
        with pipeline_job.lock:
            if pipeline_job.running:
                raise HTTPException(status_code=409, detail="流水线正在运行中")
            qq = body.qq or cfg.active_qq
            if not qq:
                raise HTTPException(status_code=400, detail="请指定 QQ 号或在 .env 设置 ACTIVE_QQ")
            selected = body.steps or _pipeline.STEP_IDS
            bad = [s for s in selected if s not in _pipeline.STEP_IDS]
            if bad:
                raise HTTPException(status_code=400, detail=f"未知步骤: {bad}")
            meta = {m["id"]: m for m in _pipeline.pipeline_steps()}
            # Atomic check-then-start under the held lock (mirrors BackgroundJob.start).
            pipeline_job.running = True
            pipeline_job.ok = None
            pipeline_job.logs = []
            pipeline_job.started_at = _jobs_now()
            pipeline_job.finished_at = None
            pipeline_job.update_extra_locked(
                qq=str(qq), stopped_at=None,
                steps=[{"id": sid, "title": meta[sid]["title"], "status": "pending", "error": None}
                       for sid in _pipeline.STEP_IDS if sid in selected],
            )
        threading.Thread(
            target=_run_pipeline_bg,
            args=(str(qq), selected, body.ptt_dir, not body.continue_on_error),
            daemon=True,
        ).start()
        return {"success": True, "qq": str(qq), "steps": selected}

    @router.get("/api/pipeline/status")
    async def api_pipeline_status():
        return pipeline_job.snapshot()

    # ---- model catalog / on-demand download ---------------------------------
    def _dl_log(msg: str) -> None:
        dl_job.log(msg)

    def _run_download_bg(name: str) -> None:
        try:
            res = _models.download_model(cfg, name, on_log=_dl_log)
            dl_job.set_extra(error=res.get("error"))
            dl_job.finish(ok=bool(res.get("ok")))
        except Exception as e:  # noqa: BLE001 — never leave 'running' stuck
            _dl_log(f"[fatal] {type(e).__name__}: {e}")
            dl_job.set_extra(error=str(e))
            dl_job.finish(ok=False)

    @router.get("/api/models/catalog")
    async def api_models_catalog():
        return {"models": cfg.model_catalog(), "default": cfg.model_dir.name}

    @router.post("/api/models/download")
    async def api_models_download(body: ModelDownload):
        with dl_job.lock:
            if dl_job.running:
                raise HTTPException(status_code=409, detail=f"正在下载 {dl_job.extra.get('name')}，请稍候")
            if not cfg.model_repo_id(body.name):
                raise HTTPException(status_code=400, detail=f"未知模型: {body.name}")
            # Atomic check-then-start: mutate under the held lock (mirrors start()).
            dl_job.running = True
            dl_job.ok = None
            dl_job.logs = []
            dl_job.started_at = _jobs_now()
            dl_job.finished_at = None
            dl_job.update_extra_locked(name=body.name, error=None)
        threading.Thread(target=_run_download_bg, args=(body.name,), daemon=True).start()
        return {"success": True, "name": body.name}

    @router.get("/api/models/download/status")
    async def api_models_download_status():
        return dl_job.snapshot()

    return router
