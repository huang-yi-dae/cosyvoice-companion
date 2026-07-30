"""CosyVoice Web Application — FastAPI backend for voice cloning.

Config-driven: all paths and the active user come from voicekit.config (YAML +
.env). No hardcoded absolute paths or QQ numbers.
"""

import sys
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

# internal/src/web/app.py -> add internal/src for the voicekit package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from voicekit import load_config
from voicekit.cosyvoice_engine import CosyVoiceEngine

# ---- configuration -----------------------------------------------------------
cfg = load_config()

WAV_DIR = cfg.user_path("voices_wav")
CLONED_DIR = cfg.user_path("voices_cloned")
OUTPUT_DIR = cfg.shared_path("web_output", create=True)
SAVED_DIR = cfg.shared_path("saved", create=True)

CATEGORY_ORIGINAL = "原始语音"
CATEGORY_CLONED = "克隆音色"
CATEGORY_DIRS = {
    CATEGORY_ORIGINAL: WAV_DIR,
    CATEGORY_CLONED: CLONED_DIR,
}

app = FastAPI(title="CosyVoice Web App")

# ---- model -------------------------------------------------------------------
print("Loading CosyVoice model...")
engine = CosyVoiceEngine(cfg)
engine.load()
print("Model loaded!")

import soundfile as sf  # noqa: E402 — after engine sets up sys.path


def get_voice_files():
    """List available voice files from the active user's directories."""
    voices = []
    for category, directory in CATEGORY_DIRS.items():
        if not directory.exists():
            continue
        for f in sorted(directory.iterdir()):
            if f.suffix.lower() not in (".wav", ".mp3"):
                continue
            try:
                data, sr = sf.read(str(f))
                if len(data.shape) > 1:
                    data = data[:, 0]
                duration = len(data) / sr
            except Exception:
                duration = 0
            display_name = f.name
            if f.name.startswith("cloned_"):
                display_name = f"克隆音色 {f.stem[:16]}..."
            elif f.name.startswith("0"):
                display_name = f"原始语音 {f.stem[:8]}..."
            voices.append({
                "id": f"{category}:{f.name}",
                "name": display_name,
                "category": category,
                "path": str(f),
                "size": f.stat().st_size,
                "duration": round(duration, 1),
            })
    return voices


def resolve_voice_path(voice_id: str) -> Path:
    """Map a 'category:filename' voice id to an absolute path."""
    if ":" in voice_id:
        category, filename = voice_id.split(":", 1)
        directory = CATEGORY_DIRS.get(category, WAV_DIR)
        return directory / filename
    return WAV_DIR / f"{voice_id}.wav"


class TTSRequest(BaseModel):
    text: str
    voice_id: str
    prompt_text: Optional[str] = None


@app.get("/")
async def root():
    return FileResponse(str(cfg.index_html))


@app.get("/api/voices")
async def list_voices():
    return {"voices": get_voice_files()}


@app.post("/api/generate")
async def generate_speech(request: TTSRequest):
    try:
        voice_path = resolve_voice_path(request.voice_id)
        if not voice_path.exists():
            raise HTTPException(status_code=404, detail=f"Voice file not found: {voice_path}")

        filename = f"{uuid.uuid4().hex[:8]}.wav"
        output_path = OUTPUT_DIR / filename
        engine.clone_to_file(request.text, voice_path, output_path, request.prompt_text)

        data, sr = sf.read(str(output_path))
        duration = len(data) / sr
        return {
            "success": True,
            "filename": filename,
            "duration": round(duration, 1),
            "size": output_path.stat().st_size,
            "url": f"/api/audio/{filename}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/audio/{filename}")
async def get_audio(filename: str):
    filepath = OUTPUT_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(str(filepath), media_type="audio/wav")


@app.get("/api/voice/{voice_id:path}")
async def get_voice_file(voice_id: str):
    filepath = resolve_voice_path(voice_id)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Voice file not found: {filepath}")
    media_type = "audio/wav" if filepath.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(str(filepath), media_type=media_type)


@app.post("/api/save/{filename}")
async def save_audio(filename: str):
    src = OUTPUT_DIR / filename
    if not src.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    shutil.copy2(str(src), str(SAVED_DIR / filename))
    return {"success": True, "message": "Audio saved"}


@app.get("/api/saved")
async def list_saved():
    files = []
    for f in sorted(SAVED_DIR.glob("*.wav")):
        stat = f.stat()
        files.append({
            "filename": f.name,
            "size": stat.st_size,
            "time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return {"files": files}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=cfg.web["host"], port=int(cfg.web["port"]))
