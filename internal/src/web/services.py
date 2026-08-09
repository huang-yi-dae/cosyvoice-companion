"""Model / provider / LLM singletons for the web app.

Extracted from app.py (architecture review P1: 947-line single file). These are
lazily-loaded, cached backends that depend only on the resolved ``Config`` —
they have no coupling to FastAPI routes, so isolating them here gives app.py a
clean seam and makes the heavy backends independently testable/mockable.

- get_engine(cfg, name)        -> local CosyVoice engine (single-slot cache)
- get_dashscope_provider(cfg)  -> cloud TTS provider (cached)
- get_llm_client(cfg)          -> roleplay chat client (cached)
- providers_info(cfg)          -> front-end provider metadata

Caches are module-level singletons keyed for a single running server, matching
the previous in-app.py behaviour exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Be self-sufficient: ensure the voicekit package (internal/src) is importable
# even if this module is imported before app.py sets up sys.path.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from voicekit.cosyvoice_engine import CosyVoiceEngine
from voicekit.dashscope_tts import DashScopeTTSProvider
from voicekit.llm import LLMClient

# ---- lazy, single-slot engine cache -----------------------------------------
_engines: dict = {}


def get_engine(cfg, model_name: Optional[str] = None) -> CosyVoiceEngine:
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


def get_dashscope_provider(cfg) -> DashScopeTTSProvider:
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


# ---- roleplay chat LLM cache -------------------------------------------------
_llm_client: dict = {}


def get_llm_client(cfg) -> LLMClient:
    """Return a cached roleplay chat client (raises if API key missing)."""
    if "c" not in _llm_client:
        lcfg = cfg.llm_cfg()
        _llm_client["c"] = LLMClient(
            api_key=cfg.dashscope_api_key,
            model=lcfg.get("model") or "qwen-plus",
            max_turns=int(lcfg.get("max_turns", 6)),
        )
    return _llm_client["c"]


def providers_info(cfg) -> dict:
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
