"""Audio file routes: generated-output serving, saving, and voice-file access.

Extracted from app.py (architecture review §4). These routes serve/persist WAV
files under the shared output/saved dirs and stream enrolled voice samples.

Dependencies are passed in explicitly so this module never imports app.py:
- ``output_dir`` / ``saved_dir``: the shared web-output / saved Path dirs.
- ``resolve_voice_path(voice_id, qq)``: resolver injected as a callable to avoid
  pulling app.py's user-config path helpers (user_cfg/category_dirs) in here.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


def build_router(
    output_dir: Path,
    saved_dir: Path,
    resolve_voice_path: Callable[[str, Optional[str]], Path],
) -> APIRouter:
    """Build the audio-file router bound to the shared dirs + voice resolver."""
    router = APIRouter(tags=["audio"])

    @router.get("/api/voice/{voice_id:path}")
    async def get_voice_file(voice_id: str, qq: Optional[str] = None):
        filepath = resolve_voice_path(voice_id, qq)
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"Voice file not found: {filepath}")
        media_type = "audio/wav" if filepath.suffix.lower() == ".wav" else "audio/mpeg"
        return FileResponse(str(filepath), media_type=media_type)

    @router.get("/api/audio/{filename}")
    async def get_audio(filename: str):
        filepath = output_dir / filename
        if not filepath.exists():
            raise HTTPException(status_code=404, detail="Audio file not found")
        return FileResponse(str(filepath), media_type="audio/wav")

    @router.post("/api/save/{filename}")
    async def save_audio(filename: str):
        src = output_dir / filename
        if not src.exists():
            raise HTTPException(status_code=404, detail="Audio file not found")
        shutil.copy2(str(src), str(saved_dir / filename))
        return {"success": True, "message": "Audio saved"}

    @router.get("/api/saved")
    async def list_saved():
        files = []
        for f in sorted(saved_dir.glob("*.wav")):
            stat = f.stat()
            files.append({
                "filename": f.name,
                "size": stat.st_size,
                "time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        return {"files": files}

    return router
