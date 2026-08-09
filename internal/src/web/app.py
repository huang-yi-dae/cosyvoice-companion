"""CosyVoice Web Application — FastAPI backend for voice cloning + management.

Config-driven: all paths, the active user, available users/models and per-user
data come from voicekit.config (YAML + .env). No hardcoded absolute paths or QQ
numbers. The CosyVoice model is loaded lazily on first synthesis so the UI and
the management console stay responsive without waiting for the model.
"""

import re
import sys
import json
import hmac
from pathlib import Path
from typing import List, Optional

# internal/src/web/app.py -> add internal/src for the voicekit package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from voicekit import load_config
from voicekit.audio import concat_wavs
from voicekit.wavstream import wav_stream

# Backend singletons (engine / cloud provider / chat LLM / providers_info) live
# in services.py — architecture review P1: keep app.py a thin composition root.
# They take an explicit cfg; thin wrappers below bind the module-level cfg so
# route handlers keep calling get_engine()/... unchanged.
import services as _services

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


# ---- backend singletons: thin wrappers delegating to services.py -------------
# (Caches now live in services.py; these bind the module-level cfg so all route
#  handlers keep their existing call signatures — behaviour is identical.)
def get_engine(model_name: Optional[str] = None):
    """Return a loaded local engine for ``model_name`` (cached, single-slot)."""
    return _services.get_engine(cfg, model_name)


def get_dashscope_provider():
    """Return a cached DashScope cloud provider (raises if key/config missing)."""
    return _services.get_dashscope_provider(cfg)


def get_llm_client():
    """Return a cached roleplay chat client (raises if API key missing)."""
    return _services.get_llm_client(cfg)


def providers_info() -> dict:
    """Per-provider metadata for the front end (types, voices, key status)."""
    return _services.providers_info(cfg)


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
# TTSRequest moved to routers/synth.py (its only consumers were the generate
# routes). Response models below stay here (API contract + /docs).


# ---- response models (API contract + auto OpenAPI docs at /docs; review P1) --
# extra="allow" keeps them documentation-first without rejecting current shapes.
from pydantic import ConfigDict  # noqa: E402


class VoiceItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    category: str
    duration: float


class VoicesResponse(BaseModel):
    voices: List[VoiceItem]


class UserItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    qq: str
    voice_count: int
    cloned_count: int
    has_chat_log: bool
    is_active: bool


class UsersResponse(BaseModel):
    users: List[UserItem]


class ModelItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    available: bool
    is_default: bool


class ModelsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    models: List[ModelItem]
    default: str


class KnowledgePaths(BaseModel):
    qq: str
    paths: List[str]


# PromptBody / ChatMessage / ChatRequest moved to routers/chat.py (their only
# consumers were the chat + prompt routes now living there).


# ---- pages -------------------------------------------------------------------
# Static page routes live in routers/pages.py (architecture review §4). They
# depend only on cfg, so they were the safest first slice to extract.
from routers import pages as _pages_router  # noqa: E402

app.include_router(_pages_router.build_router(cfg))


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


@app.get("/api/users", response_model=UsersResponse)
async def api_users():
    return {"users": cfg.list_users()}


@app.get("/api/models", response_model=ModelsResponse)
async def api_models():
    return {"models": cfg.list_models(), "default": cfg.model_dir.name}


# ---- voices ------------------------------------------------------------------
@app.get("/api/voices", response_model=VoicesResponse)
async def list_voices(qq: Optional[str] = None):
    return {"voices": list_voice_files(qq)}


# ---- audio file serving / saving / voice-file access -------------------------
# Extracted to routers/audio.py (architecture review §4). resolve_voice_path is
# injected as a callable so the router doesn't import app.py's path helpers.
from routers import audio as _audio_router  # noqa: E402

app.include_router(
    _audio_router.build_router(OUTPUT_DIR, SAVED_DIR, resolve_voice_path)
)


# ---- cloud voice management (DashScope enrollment, advanced) -----------------
# Extracted to routers/cloud_voices.py (architecture review §4); depends only on
# cfg + the get_dashscope_provider accessor, so it's a clean self-contained slice.
from routers import cloud_voices as _cloud_voices_router  # noqa: E402

app.include_router(_cloud_voices_router.build_router(cfg, get_dashscope_provider))


# ---- generation (extracted to routers/synth.py; heavy: engine/cloud) ---------
# All backends are injected as callables so synth.py never imports app.py.
from routers import synth as _synth_router  # noqa: E402

app.include_router(
    _synth_router.build_router(
        cfg, OUTPUT_DIR, get_engine, get_dashscope_provider,
        resolve_voice_path, concat_wavs, wav_stream,
    )
)


# ---- companion chat + per-user messages/prompt ------------------------------
# Extracted to routers/chat.py (architecture review §4). Pure-logic helpers stay
# here and are injected as callables so the router never imports app.py.
from routers import chat as _chat_router  # noqa: E402

app.include_router(
    _chat_router.build_router(
        cfg,
        voice_messages=voice_messages,
        existing_prompt=existing_prompt,
        default_prompt=default_prompt,
        regenerate_prompt=regenerate_prompt,
        load_state=load_state,
        save_state=save_state,
        get_llm_client=get_llm_client,
    )
)


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


# ---- background tasks: pipeline + model download -----------------------------
# These routes drive long-running background threads whose status lives in a
# BackgroundJob. Extracted into routers/tasks.py (architecture review §4); the
# router builds its own job instances and binds cfg via build_router(cfg).
from routers import tasks as _tasks_router  # noqa: E402

app.include_router(_tasks_router.build_router(cfg))


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
