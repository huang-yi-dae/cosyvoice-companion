"""CosyVoice Web Application — FastAPI backend for voice cloning + management.

Config-driven: all paths, the active user, available users/models and per-user
data come from voicekit.config (YAML + .env). No hardcoded absolute paths or QQ
numbers. The CosyVoice model is loaded lazily on first synthesis so the UI and
the management console stay responsive without waiting for the model.
"""

import re
import sys
import json
import uuid
import hmac
import shutil
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Optional

# internal/src/web/app.py -> add internal/src for the voicekit package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from voicekit import load_config
from voicekit.audio import concat_wavs
from voicekit.cosyvoice_engine import CosyVoiceEngine
from voicekit.dashscope_tts import DashScopeTTSProvider
from voicekit.wavstream import wav_stream

# ---- configuration -----------------------------------------------------------
cfg = load_config()

CATEGORY_ORIGINAL = "原始语音"
CATEGORY_CLONED = "克隆音色"

OUTPUT_DIR = cfg.shared_path("web_output", create=True)
SAVED_DIR = cfg.shared_path("saved", create=True)

app = FastAPI(title="CosyVoice Studio")

# ---- optional access-token auth ---------------------------------------------
# When WEB_AUTH_TOKEN (.env) or web.auth_token (yaml) is set, every request must
# present the token via one of: ``?token=`` (persisted to a cookie on success),
# ``Authorization: Bearer <token>`` header, or the ``access_token`` cookie.
# When unset, no auth is enforced and the server should bind to localhost only.
_AUTH_TOKEN = cfg.web_auth_token()

_LOGIN_HTML = (
    "<!doctype html><meta charset=utf-8><title>需要访问令牌</title>"
    "<div style='max-width:320px;margin:18vh auto;font-family:sans-serif'>"
    "<h3>请输入访问令牌</h3>"
    "<form onsubmit=\"location.search='?token='+encodeURIComponent(t.value);return false\">"
    "<input id=t type=password style='width:100%;padding:8px' placeholder='访问令牌'>"
    "<button style='margin-top:8px;padding:8px 16px'>进入</button></form></div>"
)


def _token_ok(request: Request) -> bool:
    supplied = request.query_params.get("token")
    if not supplied:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            supplied = auth[7:]
    if not supplied:
        supplied = request.cookies.get("access_token")
    return bool(supplied) and hmac.compare_digest(supplied, _AUTH_TOKEN)


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Gate every request behind the configured access token (if any)."""

    async def dispatch(self, request: Request, call_next):
        if not _AUTH_TOKEN:
            return await call_next(request)
        if not _token_ok(request):
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "未授权：需要有效访问令牌"}, status_code=401)
            return HTMLResponse(_LOGIN_HTML, status_code=401)
        response = await call_next(request)
        # First-time ?token= login: persist to a cookie so links keep working.
        if request.query_params.get("token"):
            response.set_cookie("access_token", _AUTH_TOKEN, httponly=True, samesite="lax")
        return response


if _AUTH_TOKEN:
    app.add_middleware(TokenAuthMiddleware)

if cfg.static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(cfg.static_dir)), name="static")


# ---- lazy, single-slot engine cache -----------------------------------------
_engines: dict = {}


def get_engine(model_name: Optional[str] = None) -> CosyVoiceEngine:
    """Return a loaded engine for ``model_name`` (cached, single-slot)."""
    model_dir = cfg.model_path(model_name)
    key = model_dir.name
    if key not in _engines:
        _engines.clear()  # keep only one model in memory at a time
        print(f"Loading CosyVoice model: {key} ...")
        eng = CosyVoiceEngine(cfg, model_dir=model_dir)
        eng.load()
        print("Model loaded!")
        _engines[key] = eng
    return _engines[key]


# ---- cloud (DashScope) provider cache ---------------------------------------
_dashscope_provider: dict = {}


def get_dashscope_provider() -> DashScopeTTSProvider:
    """Return a cached DashScope cloud provider (raises if key/config missing)."""
    if "p" not in _dashscope_provider:
        dcfg = cfg.dashscope_cfg()
        _dashscope_provider["p"] = DashScopeTTSProvider(
            api_key=cfg.dashscope_api_key,
            target_model=dcfg.get("target_model", "cosyvoice-v3.5-flash"),
            region=dcfg.get("region", "cn-beijing"),
            voices=cfg.dashscope_voices(),
            oss=dcfg.get("oss", {}),
        )
    return _dashscope_provider["p"]


def providers_info() -> dict:
    """Per-provider metadata for the front end (types, voices, key status)."""
    dcfg = cfg.dashscope_cfg()
    return {
        "default": cfg.tts_provider_default(),
        "local": {
            "type": "cosyvoice_local",
            "needs_reference": True,
            "label": "本地模型",
        },
        "dashscope": {
            "type": "dashscope",
            "needs_reference": False,
            "label": "阿里云百炼（云端）",
            "configured": bool(cfg.dashscope_api_key),
            "target_model": dcfg.get("target_model", "cosyvoice-v3.5-flash"),
            "voices": cfg.dashscope_voices(),
        },
    }


# ---- per-user helpers --------------------------------------------------------
def user_cfg(qq: Optional[str]):
    """Return a config bound to ``qq`` (falls back to the active user)."""
    return cfg.with_user(qq) if qq else cfg


def category_dirs(ucfg) -> dict:
    return {
        CATEGORY_ORIGINAL: ucfg.user_path("voices_wav"),
        CATEGORY_CLONED: ucfg.user_path("voices_cloned"),
    }


def list_voice_files(qq: Optional[str]) -> List[dict]:
    import soundfile as sf

    ucfg = user_cfg(qq)
    voices: List[dict] = []
    for category, directory in category_dirs(ucfg).items():
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
            voices.append({
                "id": f"{category}:{f.name}",
                "name": f.name,
                "category": category,
                "size": f.stat().st_size,
                "duration": round(duration, 1),
            })
    return voices


def resolve_voice_path(voice_id: str, qq: Optional[str]) -> Path:
    ucfg = user_cfg(qq)
    dirs = category_dirs(ucfg)
    if ":" in voice_id:
        category, filename = voice_id.split(":", 1)
        directory = dirs.get(category, dirs[CATEGORY_ORIGINAL])
        return directory / filename
    return dirs[CATEGORY_ORIGINAL] / f"{voice_id}.wav"


# ---- persisted web state (knowledge paths, prompt overrides) -----------------
def load_state() -> dict:
    p = cfg.state_file
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    p = cfg.state_file
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- chat-log parsing --------------------------------------------------------
AMR_RE = re.compile(r"[0-9a-fA-F]{8,}\.amr")
# keep CJK, latin, digits, spaces and common punctuation; drop binary noise
CLEAN_RE = re.compile(r"[^\u4e00-\u9fff0-9A-Za-z \u3000，。？！、,.?!~…—\-]")


def clean_text(s: str) -> str:
    return CLEAN_RE.sub("", s or "").strip()


def load_chat_messages(qq: str) -> list:
    path = cfg.find_chat_log(qq)
    if not path:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data.get("messages", data) if isinstance(data, dict) else data


def voice_messages(qq: str) -> List[dict]:
    ucfg = user_cfg(qq)
    wav_dir = ucfg.user_path("voices_wav")
    wav_stems = {p.stem for p in wav_dir.glob("*.wav")} if wav_dir.exists() else set()

    out: List[dict] = []
    for m in load_chat_messages(qq):
        if m.get("type") != "voice":
            continue
        if str(m.get("sender")) != str(qq):
            continue
        amr = AMR_RE.search(str(m.get("content", "")))
        amr_name = amr.group(0) if amr else None
        stem = Path(amr_name).stem if amr_name else None
        has_wav = stem in wav_stems if stem else False
        out.append({
            "time": m.get("time", ""),
            "file": amr_name,
            "has_wav": has_wav,
            "voice_id": f"{CATEGORY_ORIGINAL}:{stem}.wav" if has_wav else None,
        })
    return out


# ---- roleplay prompt ---------------------------------------------------------
def default_prompt(qq: str) -> str:
    return (
        "你现在要扮演一个人。你不是 AI，你就是这个人。\n\n"
        "## 你是谁\n你正在和一个你在意的人聊天，"
        "你的聊天风格是从真实聊天记录中学习的。\n\n"
        "## 核心性格\n- <性格要点，可在管理页重新生成>\n\n"
        "## 严格遵守的规则\n1. 回复简短、口语化。\n2. 保持一致的语气。\n"
    )


def existing_prompt(qq: str) -> Optional[dict]:
    """Prompt from saved override, then any private/agents SystemPrompt.txt."""
    state = load_state()
    override = state.get("prompts", {}).get(str(qq))
    if override:
        return {"content": override, "source": "override"}
    for agent in cfg.list_agents():
        sp = cfg.agents_root / agent / "SystemPrompt.txt"
        if sp.exists():
            return {"content": sp.read_text(encoding="utf-8"), "source": f"agents/{agent}"}
    return None


def regenerate_prompt(qq: str) -> str:
    """Derive a roleplay System Prompt from the user's own text messages."""
    import collections

    texts = [
        clean_text(m.get("content", ""))
        for m in load_chat_messages(qq)
        if m.get("type") == "text" and str(m.get("sender")) == str(qq)
    ]
    texts = [t for t in texts if t]
    total = len(texts)
    if not total:
        return default_prompt(qq)

    avg_len = sum(len(t) for t in texts) / total
    short = [t for t in texts if len(t) <= 6]
    top_short = [w for w, _ in collections.Counter(short).most_common(12)]
    excl = sum(t.count("！") + t.count("!") for t in texts)
    excl_ratio = excl / total

    style_len = "极简（多为短句/短语）" if avg_len < 10 else (
        "简短" if avg_len < 20 else "中等长度")
    excl_note = "几乎不用感叹号，语气克制" if excl_ratio < 0.05 else "情绪外放，常用感叹号"

    common = "、".join(top_short) if top_short else "（无高频短语）"
    return (
        "你现在要扮演一个人。你不是 AI，你就是这个人。\n\n"
        "## 你是谁\n"
        "你正在和一个你在意的人聊天。以下风格从真实聊天记录中统计得出。\n\n"
        "## 语言风格\n"
        f"- 回复长度：{style_len}（平均约 {avg_len:.0f} 字）\n"
        f"- 标点习惯：{excl_note}\n"
        f"- 高频短语（可直接使用）：{common}\n\n"
        "## 严格遵守的规则\n"
        "1. 回复保持上面统计出的长度与语气，不要长篇大论。\n"
        "2. 使用高频短语，贴近真实说话方式。\n"
        "3. 不寒暄、不客套、不用讨好语气。\n\n"
        f"（基于 {total} 条本人文本消息自动生成，可在管理页手动微调后保存。）"
    )


# ---- models ------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    voice_ids: List[str] = []
    qq: Optional[str] = None
    model: Optional[str] = None
    prompt_text: Optional[str] = None
    language: Optional[str] = None
    provider: Optional[str] = None
    voice: Optional[str] = None


class PromptBody(BaseModel):
    content: str


class KnowledgePaths(BaseModel):
    qq: str
    paths: List[str]


# ---- pages -------------------------------------------------------------------
@app.get("/")
async def root():
    return FileResponse(str(cfg.index_html))


@app.get("/manage")
async def manage():
    return FileResponse(str(cfg.manage_html))


@app.get("/pipeline")
async def pipeline_page():
    return FileResponse(str(cfg.pipeline_html))


@app.get("/models")
async def models_page():
    return FileResponse(str(cfg.models_html))


# ---- config / users / models -------------------------------------------------
@app.get("/api/config")
async def get_config():
    return {
        "active_qq": cfg.active_qq,
        "default_prompt_text": cfg.default_prompt_text,
        "default_model": cfg.model_dir.name,
        "languages": cfg.languages(),
        "providers": providers_info(),
    }


@app.get("/api/users")
async def api_users():
    return {"users": cfg.list_users()}


@app.get("/api/models")
async def api_models():
    return {"models": cfg.list_models(), "default": cfg.model_dir.name}


# ---- voices ------------------------------------------------------------------
@app.get("/api/voices")
async def list_voices(qq: Optional[str] = None):
    return {"voices": list_voice_files(qq)}


@app.get("/api/voice/{voice_id:path}")
async def get_voice_file(voice_id: str, qq: Optional[str] = None):
    filepath = resolve_voice_path(voice_id, qq)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Voice file not found: {filepath}")
    media_type = "audio/wav" if filepath.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(str(filepath), media_type=media_type)


# ---- cloud voice management (DashScope enrollment, advanced) -----------------
class CloudVoiceCreate(BaseModel):
    audio_url: str
    prefix: str = "voice"
    language_hint: Optional[str] = None


@app.get("/api/cloud/voices")
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


@app.post("/api/cloud/voices")
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


@app.delete("/api/cloud/voices/{voice_id}")
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


# ---- generation (sync -> runs in threadpool; model load is heavy) ------------
@app.post("/api/generate")
def generate_speech(request: TTSRequest):
    import soundfile as sf

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="文本不能为空")

    provider_name = request.provider or cfg.tts_provider_default()
    filename = f"{uuid.uuid4().hex[:8]}.wav"
    output_path = OUTPUT_DIR / filename

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
            OUTPUT_DIR / f"ref_{uuid.uuid4().hex[:8]}.wav",
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
        OUTPUT_DIR / f"ref_{uuid.uuid4().hex[:8]}.wav",
        target_sr=cfg.target_sr,
    )


@app.post("/api/generate/stream")
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
            tmp = OUTPUT_DIR / f"{uuid.uuid4().hex[:8]}.wav"
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


@app.get("/api/audio/{filename}")
async def get_audio(filename: str):
    filepath = OUTPUT_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(str(filepath), media_type="audio/wav")


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


# ---- management: messages / prompt / knowledge paths -------------------------
@app.get("/api/users/{qq}/messages")
async def api_messages(qq: str):
    msgs = voice_messages(qq)
    return {"qq": qq, "count": len(msgs), "messages": msgs}


@app.get("/api/users/{qq}/prompt")
async def api_get_prompt(qq: str):
    found = existing_prompt(qq)
    if found:
        return {"qq": qq, **found}
    return {"qq": qq, "content": default_prompt(qq), "source": "default"}


@app.post("/api/users/{qq}/prompt")
async def api_save_prompt(qq: str, body: PromptBody):
    state = load_state()
    state.setdefault("prompts", {})[str(qq)] = body.content
    save_state(state)
    return {"success": True, "source": "override"}


@app.post("/api/users/{qq}/prompt/regenerate")
async def api_regen_prompt(qq: str):
    content = regenerate_prompt(qq)
    state = load_state()
    state.setdefault("prompts", {})[str(qq)] = content
    save_state(state)
    return {"success": True, "content": content, "source": "regenerated"}


@app.get("/api/knowledge-paths")
async def api_get_knowledge(qq: Optional[str] = None):
    state = load_state()
    saved = state.get("knowledge_paths", {}).get(str(qq), []) if qq else []
    discovered = []
    for agent in cfg.list_agents():
        kb = cfg.agents_root / agent / "knowledge-base"
        if kb.exists():
            n = len(list(kb.glob("*")))
            discovered.append({"path": str(kb), "label": f"agents/{agent}/knowledge-base", "files": n})
    ureports = user_cfg(qq).user_dir() / "reports" if qq else None
    if ureports and ureports.exists():
        discovered.append({"path": str(ureports), "label": f"users/{qq}/reports", "files": len(list(ureports.glob('*')))})
    return {"qq": qq, "paths": saved, "discovered": discovered}


@app.post("/api/knowledge-paths")
async def api_save_knowledge(body: KnowledgePaths):
    state = load_state()
    state.setdefault("knowledge_paths", {})[str(body.qq)] = body.paths
    save_state(state)
    return {"success": True, "count": len(body.paths)}


# ---- automation pipeline -----------------------------------------------------
from voicekit import pipeline as _pipeline  # noqa: E402  (grouped lazy import; see roadmap #3)

_MAX_LOGS = 500
_pipeline_lock = threading.Lock()
_pipeline_state: dict = {
    "running": False,
    "qq": None,
    "steps": [],
    "logs": [],
    "ok": None,
    "stopped_at": None,
    "started_at": None,
    "finished_at": None,
}


class PipelineStart(BaseModel):
    qq: Optional[str] = None
    steps: Optional[List[str]] = None
    ptt_dir: Optional[str] = None
    continue_on_error: bool = False


def _pipeline_event(event: dict) -> None:
    """Update shared pipeline state from a run_pipeline event (thread-safe)."""
    with _pipeline_lock:
        etype = event.get("type")
        if etype == "log":
            logs = _pipeline_state["logs"]
            logs.append(event.get("message", ""))
            del logs[:-_MAX_LOGS]
        elif etype == "step":
            sid = event.get("id")
            for s in _pipeline_state["steps"]:
                if s["id"] == sid:
                    s["status"] = event.get("status", s["status"])
                    if event.get("error"):
                        s["error"] = event["error"]
                    break
        elif etype == "done":
            _pipeline_state["running"] = False
            _pipeline_state["ok"] = event.get("ok")
            _pipeline_state["stopped_at"] = event.get("stopped_at")
            _pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _run_pipeline_bg(qq: str, step_ids, ptt_dir, stop_on_error) -> None:
    try:
        _pipeline.run_pipeline(
            cfg, qq=qq, step_ids=step_ids, on_event=_pipeline_event,
            ptt_dir=ptt_dir, stop_on_error=stop_on_error,
        )
    except Exception as e:  # noqa: BLE001 — record crash, never leave 'running' stuck
        _pipeline_event({"type": "log", "message": f"[fatal] {type(e).__name__}: {e}"})
        _pipeline_event({"type": "done", "ok": False, "stopped_at": None})


@app.get("/api/pipeline/steps")
async def api_pipeline_steps():
    return {"steps": _pipeline.pipeline_steps()}


@app.post("/api/pipeline/start")
async def api_pipeline_start(body: PipelineStart):
    with _pipeline_lock:
        if _pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="流水线正在运行中")
        qq = body.qq or cfg.active_qq
        if not qq:
            raise HTTPException(status_code=400, detail="请指定 QQ 号或在 .env 设置 ACTIVE_QQ")
        selected = body.steps or _pipeline.STEP_IDS
        bad = [s for s in selected if s not in _pipeline.STEP_IDS]
        if bad:
            raise HTTPException(status_code=400, detail=f"未知步骤: {bad}")
        meta = {m["id"]: m for m in _pipeline.pipeline_steps()}
        _pipeline_state.update(
            running=True, qq=str(qq), ok=None, stopped_at=None, logs=[],
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), finished_at=None,
            steps=[{"id": sid, "title": meta[sid]["title"], "status": "pending", "error": None}
                   for sid in _pipeline.STEP_IDS if sid in selected],
        )
    thread = threading.Thread(
        target=_run_pipeline_bg,
        args=(str(qq), selected, body.ptt_dir, not body.continue_on_error),
        daemon=True,
    )
    thread.start()
    return {"success": True, "qq": str(qq), "steps": selected}


@app.get("/api/pipeline/status")
async def api_pipeline_status():
    with _pipeline_lock:
        return json.loads(json.dumps(_pipeline_state))  # shallow snapshot copy


# ---- model catalog / on-demand download --------------------------------------
from voicekit import models as _models  # noqa: E402  (grouped lazy import; see roadmap #3)

_dl_lock = threading.Lock()
_dl_state: dict = {
    "running": False,
    "name": None,
    "ok": None,
    "error": None,
    "logs": [],
    "started_at": None,
    "finished_at": None,
}


class ModelDownload(BaseModel):
    name: str


def _dl_log(msg: str) -> None:
    with _dl_lock:
        logs = _dl_state["logs"]
        logs.append(msg)
        del logs[:-_MAX_LOGS]


def _run_download_bg(name: str) -> None:
    try:
        res = _models.download_model(cfg, name, on_log=_dl_log)
        with _dl_lock:
            _dl_state["ok"] = bool(res.get("ok"))
            _dl_state["error"] = res.get("error")
    except Exception as e:  # noqa: BLE001 — never leave 'running' stuck
        _dl_log(f"[fatal] {type(e).__name__}: {e}")
        with _dl_lock:
            _dl_state["ok"] = False
            _dl_state["error"] = str(e)
    finally:
        with _dl_lock:
            _dl_state["running"] = False
            _dl_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.get("/api/models/catalog")
async def api_models_catalog():
    return {"models": cfg.model_catalog(), "default": cfg.model_dir.name}


@app.post("/api/models/download")
async def api_models_download(body: ModelDownload):
    with _dl_lock:
        if _dl_state["running"]:
            raise HTTPException(status_code=409, detail=f"正在下载 {_dl_state['name']}，请稍候")
        if not cfg.model_repo_id(body.name):
            raise HTTPException(status_code=400, detail=f"未知模型: {body.name}")
        _dl_state.update(
            running=True, name=body.name, ok=None, error=None, logs=[],
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), finished_at=None,
        )
    threading.Thread(target=_run_download_bg, args=(body.name,), daemon=True).start()
    return {"success": True, "name": body.name}


@app.get("/api/models/download/status")
async def api_models_download_status():
    with _dl_lock:
        return json.loads(json.dumps(_dl_state))


if __name__ == "__main__":
    import uvicorn

    host = cfg.web["host"]
    if host not in ("127.0.0.1", "localhost") and not _AUTH_TOKEN:
        print(
            "\n[安全警告] 当前绑定到 "
            f"{host}（对局域网开放）但未设置访问令牌。"
            "\n         任何同网设备均可触发解密/合成等敏感操作。"
            "\n         请在 .env 设置 WEB_AUTH_TOKEN，或将 web.host 改为 127.0.0.1。\n"
        )
    uvicorn.run(app, host=host, port=int(cfg.web["port"]))
