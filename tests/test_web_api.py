"""Integration tests for the FastAPI web layer (architecture review P1).

The existing suite covers only pure voicekit logic; the API layer — the most
frequently changed, regression-prone surface — had zero coverage. These tests
drive the real ASGI app through Starlette's TestClient against hermetic demo
data produced by the seed script (reused as a fixture), with no GPU / network /
real model: only the read-only, model-free endpoints are exercised.

Heavy endpoints (/api/generate, /api/chat, downloads, pipeline runs) require a
model / cloud key and are intentionally out of scope here.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# The web layer needs FastAPI/Starlette, which the lightweight CI env does not
# install (it only has pytest/ruff/PyYAML/python-dotenv for pure-logic tests).
# Skip the whole module there instead of erroring at collection time.
pytest.importorskip("fastapi")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "internal" / "src"
WEB_DIR = SRC_DIR / "web"
for p in (str(SRC_DIR), str(WEB_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

DEMO_QQ = "10001"


@pytest.fixture(scope="module")
def client():
    """Seed demo data, import the app fresh, and return a TestClient.

    The app reads ACTIVE_QQ from the environment at import time, so we set it
    before importing. Seed data lands in the real (gitignored) private/ dir,
    exactly like a normal local run.
    """
    from fastapi.testclient import TestClient

    os.environ["ACTIVE_QQ"] = DEMO_QQ
    os.environ.pop("WEB_AUTH_TOKEN", None)  # ensure auth is disabled for tests
    os.environ.pop("DASHSCOPE_API_KEY", None)  # cloud-voice tests assume unconfigured

    # Generate hermetic demo data (idempotent; only touches demo QQs).
    seed = importlib.import_module("scripts.seed_demo_data")
    seed.main()

    # Import (or reload) the app so it picks up ACTIVE_QQ + seeded data.
    if "app" in sys.modules:
        app_mod = importlib.reload(sys.modules["app"])
    else:
        app_mod = importlib.import_module("app")

    with TestClient(app_mod.app) as c:
        yield c


# ---- pages render -----------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/manage", "/pipeline", "/models", "/companion"])
def test_pages_render(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


# ---- config / users / models ------------------------------------------------
def test_config_shape(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["active_qq"] == DEMO_QQ
    providers = data["providers"]
    assert set(providers) >= {"default", "local", "dashscope"}
    assert providers["local"]["type"] == "cosyvoice_local"
    assert isinstance(data["languages"], list) and data["languages"]


def test_users_lists_demo_user(client):
    r = client.get("/api/users")
    assert r.status_code == 200
    users = r.json()["users"]
    qqs = {u["qq"] for u in users}
    assert DEMO_QQ in qqs
    demo = next(u for u in users if u["qq"] == DEMO_QQ)
    assert demo["voice_count"] >= 1
    assert demo["has_chat_log"] is True


def test_models_lists_ready_model(client):
    r = client.get("/api/models")
    assert r.status_code == 200
    data = r.json()
    assert data["default"]
    assert any(m["available"] for m in data["models"])


def test_models_catalog_has_download_flags(client):
    r = client.get("/api/models/catalog")
    assert r.status_code == 200
    models = r.json()["models"]
    assert models
    for m in models:
        assert "downloaded" in m and "est_minutes" in m


# ---- voices -----------------------------------------------------------------
def test_voices_for_demo_user(client):
    r = client.get("/api/voices", params={"qq": DEMO_QQ})
    assert r.status_code == 200
    voices = r.json()["voices"]
    assert voices, "seeded demo user should have voice samples"
    v = voices[0]
    assert {"id", "name", "category", "duration"} <= set(v)


def test_voice_file_streams_wav(client):
    voices = client.get("/api/voices", params={"qq": DEMO_QQ}).json()["voices"]
    original = next(v for v in voices if v["category"] == "原始语音")
    r = client.get(f"/api/voice/{original['id']}", params={"qq": DEMO_QQ})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert len(r.content) > 44  # more than a bare WAV header


def test_voice_file_404_for_missing(client):
    r = client.get("/api/voice/原始语音:does-not-exist.wav", params={"qq": DEMO_QQ})
    assert r.status_code == 404


# ---- cloud voices (extracted to routers/cloud_voices.py) --------------------
def test_cloud_voices_unconfigured_without_api_key(client):
    """No DASHSCOPE_API_KEY in the test env → degrade to the configured list."""
    r = client.get("/api/cloud/voices")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert "voices" in body  # configured fallback list (possibly empty)


def test_cloud_voice_create_requires_api_key(client):
    r = client.post("/api/cloud/voices", json={"audio_url": "http://x/a.wav"})
    assert r.status_code == 400
    assert "DASHSCOPE_API_KEY" in r.json()["detail"]


# ---- audio files (extracted to routers/audio.py) ----------------------------
def test_audio_404_for_missing(client):
    r = client.get("/api/audio/does-not-exist.wav")
    assert r.status_code == 404


def test_save_404_for_missing_source(client):
    r = client.post("/api/save/does-not-exist.wav")
    assert r.status_code == 404


def test_saved_lists_files_shape(client):
    r = client.get("/api/saved")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["files"], list)  # possibly empty, but well-formed
    for f in body["files"]:
        assert {"filename", "size", "time"} <= set(f)


# ---- management: messages / prompt ------------------------------------------
def test_messages_link_voice_to_wav(client):
    r = client.get(f"/api/users/{DEMO_QQ}/messages")
    assert r.status_code == 200
    data = r.json()
    assert data["qq"] == DEMO_QQ
    assert data["count"] >= 1
    # At least one seeded voice message should resolve to a playable wav.
    assert any(m["has_wav"] and m["voice_id"] for m in data["messages"])


def test_prompt_from_seeded_agent(client):
    r = client.get(f"/api/users/{DEMO_QQ}/prompt")
    assert r.status_code == 200
    data = r.json()
    assert data["qq"] == DEMO_QQ
    assert data["content"].strip()
    assert data["source"]  # override / agents/... / default


def test_prompt_regenerate_from_stats(client):
    r = client.post(f"/api/users/{DEMO_QQ}/prompt/regenerate")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["content"].strip()


# ---- validation errors ------------------------------------------------------
def test_generate_rejects_empty_text(client):
    r = client.post("/api/generate", json={"text": "  ", "voice_ids": [], "qq": DEMO_QQ})
    assert r.status_code == 400


def test_generate_stream_rejects_empty_text(client):
    # /api/generate/stream extracted to routers/synth.py — same empty-text guard.
    r = client.post("/api/generate/stream", json={"text": "  ", "voice_ids": [], "qq": DEMO_QQ})
    assert r.status_code == 400
