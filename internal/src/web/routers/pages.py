"""Static page routes (architecture review §4 — extracted from app.py).

These serve the five prebuilt HTML entry points. They depend only on ``cfg``
for the file paths, so they are the safest first slice to move out of the
composition root without touching engines, services, or background jobs.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse


def build_router(cfg) -> APIRouter:
    """Build the page router bound to the given config.

    ``cfg`` supplies the resolved HTML paths (index/manage/pipeline/models/
    companion). Passed in explicitly so this module never imports app.py.
    """
    router = APIRouter(tags=["pages"])

    @router.get("/")
    async def root():
        return FileResponse(str(cfg.index_html))

    @router.get("/manage")
    async def manage():
        return FileResponse(str(cfg.manage_html))

    @router.get("/pipeline")
    async def pipeline_page():
        return FileResponse(str(cfg.pipeline_html))

    @router.get("/models")
    async def models_page():
        return FileResponse(str(cfg.models_html))

    @router.get("/companion")
    async def companion_page():
        return FileResponse(str(cfg.companion_html))

    return router
