"""Cloud voice management routes (DashScope enrollment, advanced).

Extracted from app.py (architecture review §4). These three routes list, create,
and delete DashScope-enrolled voices. They depend only on ``cfg`` (for the API
key + configured fallback list) and the ``get_dashscope_provider`` accessor, so
they are a clean self-contained slice — unlike the audio/voice-file routes,
which entangle with user-config path helpers and the synthesis engine.

``build_router(cfg, get_dashscope_provider)`` takes the provider accessor as a
callable so this module never imports app.py or services.py directly.
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class CloudVoiceCreate(BaseModel):
    audio_url: str
    prefix: str = "voice"
    language_hint: Optional[str] = None


def build_router(cfg, get_dashscope_provider: Callable) -> APIRouter:
    """Build the cloud-voice router bound to cfg + the provider accessor."""
    router = APIRouter(tags=["cloud-voices"])

    @router.get("/api/cloud/voices")
    async def api_cloud_voices():
        """List cloud voices: live enrollment list if reachable, else config list."""
        if not cfg.dashscope_api_key:
            return {"configured": False, "voices": cfg.dashscope_voices()}
        try:
            provider = get_dashscope_provider()
            voices = provider.list_voices()
            # Fall back to configured voices if the account has none enrolled yet.
            if not voices:
                voices = cfg.dashscope_voices()
            return {"configured": True, "voices": voices}
        except Exception as e:  # noqa: BLE001 — degrade to configured voices
            return {"configured": True, "voices": cfg.dashscope_voices(),
                    "error": str(e)}

    @router.post("/api/cloud/voices")
    async def api_cloud_create_voice(body: CloudVoiceCreate):
        if not cfg.dashscope_api_key:
            raise HTTPException(status_code=400, detail="未配置 DASHSCOPE_API_KEY")
        try:
            provider = get_dashscope_provider()
            voice_id = provider.create_voice(
                body.audio_url, body.prefix, body.language_hint,
            )
            return {"success": True, "voice_id": voice_id}
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/api/cloud/voices/{voice_id}")
    async def api_cloud_delete_voice(voice_id: str):
        if not cfg.dashscope_api_key:
            raise HTTPException(status_code=400, detail="未配置 DASHSCOPE_API_KEY")
        try:
            provider = get_dashscope_provider()
            provider.delete_voice(voice_id)
            return {"success": True}
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e))

    return router
