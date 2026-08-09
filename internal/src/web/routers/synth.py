"""Speech synthesis routes: /api/generate and /api/generate/stream.

Extracted from app.py (architecture review §4). These are the heaviest routes —
local zero-shot cloning loads the CosyVoice engine, the cloud path calls
DashScope — so all backends are injected via callables/values and this module
never imports app.py or the engine eagerly (soundfile is imported lazily inside
the handler, matching the previous in-app.py behaviour).

Injected dependencies (build_router):
- cfg                     : resolved Config (defaults, target_sr, language_tag)
- output_dir              : shared web-output Path
- get_engine(model)       : local CosyVoice engine accessor (lazy, cached)
- get_dashscope_provider(): cloud TTS provider accessor (cached)
- resolve_voice_path(id,qq): voice-sample path resolver
- concat_wavs / wav_stream: voicekit audio helpers
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class TTSRequest(BaseModel):
    text: str
    voice_ids: List[str] = []
    qq: Optional[str] = None
    model: Optional[str] = None
    prompt_text: Optional[str] = None
    language: Optional[str] = None
    provider: Optional[str] = None
    voice: Optional[str] = None


def build_router(
    cfg,
    output_dir: Path,
    get_engine: Callable,
    get_dashscope_provider: Callable,
    resolve_voice_path: Callable[[str, Optional[str]], Path],
    concat_wavs: Callable,
    wav_stream: Callable,
) -> APIRouter:
    """Build the synthesis router bound to cfg + backend accessors."""
    router = APIRouter(tags=["synth"])

    def _resolve_reference(request: TTSRequest) -> Path:
        """Resolve+combine the selected local voice samples into one reference WAV."""
        if not request.voice_ids:
            raise HTTPException(status_code=400, detail="请至少选择一个语音样本")
        ref_paths = []
        for vid in request.voice_ids:
            p = resolve_voice_path(vid, request.qq)
            if p.exists():
                ref_paths.append(p)
        if not ref_paths:
            raise HTTPException(status_code=404, detail="所选语音样本不存在")
        if len(ref_paths) == 1:
            return ref_paths[0]
        return concat_wavs(
            ref_paths,
            output_dir / f"ref_{uuid.uuid4().hex[:8]}.wav",
            target_sr=cfg.target_sr,
        )

    @router.post("/api/generate")
    def generate_speech(request: TTSRequest):
        import soundfile as sf

        if not request.text.strip():
            raise HTTPException(status_code=400, detail="文本不能为空")

        provider_name = request.provider or cfg.tts_provider_default()
        filename = f"{uuid.uuid4().hex[:8]}.wav"
        output_path = output_dir / filename

        # ---- cloud provider path: synthesize from a pre-registered voice id -----
        if provider_name == "dashscope":
            if not request.voice:
                raise HTTPException(status_code=400, detail="请选择一个云端音色")
            try:
                provider = get_dashscope_provider()
                provider.synthesize_to_file(
                    request.text, output_path,
                    voice=request.voice, language=request.language,
                )
                data, sr = sf.read(str(output_path))
                return {
                    "success": True,
                    "filename": filename,
                    "duration": round(len(data) / sr, 1),
                    "size": output_path.stat().st_size,
                    "url": f"/api/audio/{filename}",
                    "model": provider.name,
                    "language": request.language or "auto",
                    "samples_used": 0,
                }
            except HTTPException:
                raise
            except Exception as e:  # noqa: BLE001 — surface synth errors to the client
                raise HTTPException(status_code=500, detail=str(e))

        # ---- local provider path: zero-shot clone from reference samples --------
        if not request.voice_ids:
            raise HTTPException(status_code=400, detail="请至少选择一个语音样本")

        ref_paths = []
        for vid in request.voice_ids:
            p = resolve_voice_path(vid, request.qq)
            if p.exists():
                ref_paths.append(p)
        if not ref_paths:
            raise HTTPException(status_code=404, detail="所选语音样本不存在")

        # Combine multiple samples into a single richer reference clip.
        if len(ref_paths) == 1:
            reference = ref_paths[0]
        else:
            reference = concat_wavs(
                ref_paths,
                output_dir / f"ref_{uuid.uuid4().hex[:8]}.wav",
                target_sr=cfg.target_sr,
            )

        try:
            engine = get_engine(request.model)
            engine.synthesize_to_file(
                request.text, output_path,
                reference_wav=reference, prompt_text=request.prompt_text,
                language=request.language,
            )

            data, sr = sf.read(str(output_path))
            return {
                "success": True,
                "filename": filename,
                "duration": round(len(data) / sr, 1),
                "size": output_path.stat().st_size,
                "url": f"/api/audio/{filename}",
                "model": engine.model_dir.name,
                "language": request.language or "auto",
                "samples_used": len(ref_paths),
            }
        except Exception as e:  # noqa: BLE001 — surface synth errors to the client
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/generate/stream")
    def generate_speech_stream(request: TTSRequest):
        """Stream synthesized audio as ``audio/wav`` for progressive playback.

        Local cloning streams PCM chunks from the model as they are produced (lower
        time-to-first-audio). The cloud provider has no chunked API here, so it
        synthesizes once and the finished WAV is streamed in a single pass.
        """
        if not request.text.strip():
            raise HTTPException(status_code=400, detail="文本不能为空")

        provider_name = request.provider or cfg.tts_provider_default()

        # ---- cloud: synthesize then stream the finished file --------------------
        if provider_name == "dashscope":
            if not request.voice:
                raise HTTPException(status_code=400, detail="请选择一个云端音色")
            try:
                provider = get_dashscope_provider()
                tmp = output_dir / f"{uuid.uuid4().hex[:8]}.wav"
                provider.synthesize_to_file(
                    request.text, tmp, voice=request.voice, language=request.language,
                )
            except Exception as e:  # noqa: BLE001 — surface synth errors to the client
                raise HTTPException(status_code=500, detail=str(e))

            def _file_iter(path: Path, chunk: int = 32768):
                with open(path, "rb") as f:
                    while True:
                        block = f.read(chunk)
                        if not block:
                            break
                        yield block

            return StreamingResponse(_file_iter(tmp), media_type="audio/wav")

        # ---- local: stream PCM chunks from the model as they arrive -------------
        reference = _resolve_reference(request)
        try:
            engine = get_engine(request.model)
            language_tag = cfg.language_tag(request.language)
            pcm_chunks = engine.stream_pcm(
                request.text, reference,
                prompt_text=request.prompt_text, language_tag=language_tag,
            )
            return StreamingResponse(
                wav_stream(pcm_chunks, engine.sample_rate), media_type="audio/wav",
            )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001 — surface synth errors to the client
            raise HTTPException(status_code=500, detail=str(e))

    return router
