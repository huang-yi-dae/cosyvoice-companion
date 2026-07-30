"""Unit tests for :mod:`voicekit.config` — pure path/resolution logic.

These build a :class:`Config` directly from an in-memory dict (``minimal_raw``
fixture) so they never touch the real ``config.yaml`` or ``.env``.
"""

from __future__ import annotations

import pytest

from voicekit.config import Config, PROJECT_ROOT, load_config


def _cfg(raw: dict, **kw) -> Config:
    return Config(raw=raw, **kw)


# ---- provider / tts helpers ---------------------------------------------
def test_tts_provider_default(minimal_raw):
    assert _cfg(minimal_raw).tts_provider_default() == "local"


def test_tts_provider_default_falls_back_when_missing():
    # Missing tts.provider -> "local".
    assert _cfg({"tts": {}}).tts_provider_default() == "local"


def test_dashscope_voices_filters_entries_without_id(minimal_raw):
    voices = _cfg(minimal_raw).dashscope_voices()
    # The entry lacking an "id" must be dropped.
    assert voices == [{"id": "voice-abc", "label": "他的声音"}]


def test_language_tag_maps_known_and_unknown(minimal_raw):
    cfg = _cfg(minimal_raw)
    assert cfg.language_tag("zh") == "<|zh|>"
    assert cfg.language_tag("en") == "<|en|>"
    assert cfg.language_tag("auto") == ""
    assert cfg.language_tag(None) == ""
    assert cfg.language_tag("klingon") == ""


def test_model_clone_ready(minimal_raw):
    cfg = _cfg(minimal_raw)
    assert cfg.model_clone_ready("CosyVoice-300M") is True
    assert cfg.model_clone_ready("CosyVoice-300M-SFT") is False
    # Unknown models default to True.
    assert cfg.model_clone_ready("something-new") is True


# ---- QQ resolution -------------------------------------------------------
def test_resolve_qq_precedence(minimal_raw):
    cfg = _cfg(minimal_raw, active_qq="111")
    assert cfg.resolve_qq() == "111"
    # Explicit arg wins over active_qq.
    assert cfg.resolve_qq("222") == "222"
    # Override (via with_user) wins over active_qq but loses to explicit arg.
    bound = cfg.with_user("333")
    assert bound.resolve_qq() == "333"
    assert bound.resolve_qq("444") == "444"


def test_resolve_qq_raises_without_any_qq(minimal_raw):
    cfg = _cfg(minimal_raw, active_qq=None)
    with pytest.raises(ValueError):
        cfg.resolve_qq()


def test_user_path_templating(minimal_raw):
    cfg = _cfg(minimal_raw, active_qq="12345")
    p = cfg.user_path("voices_wav")
    assert p == cfg.private_root / "users" / "12345" / "voices" / "wav"


def test_abspath_relative_resolves_against_root(minimal_raw):
    cfg = _cfg(minimal_raw)
    assert cfg.abspath("config/config.yaml") == PROJECT_ROOT / "config" / "config.yaml"


def test_abspath_absolute_is_unchanged(minimal_raw, tmp_path):
    cfg = _cfg(minimal_raw)
    assert cfg.abspath(str(tmp_path)) == tmp_path


# ---- web access token ----------------------------------------------------
def test_web_auth_token_none_by_default(minimal_raw, monkeypatch):
    monkeypatch.delenv("WEB_AUTH_TOKEN", raising=False)
    # No web block at all -> None.
    assert _cfg(minimal_raw).web_auth_token() is None


def test_web_auth_token_from_yaml(minimal_raw, monkeypatch):
    monkeypatch.delenv("WEB_AUTH_TOKEN", raising=False)
    raw = dict(minimal_raw)
    raw["web"] = {"auth_token": "yaml-secret"}
    assert _cfg(raw).web_auth_token() == "yaml-secret"


def test_web_auth_token_env_overrides_yaml(minimal_raw, monkeypatch):
    monkeypatch.setenv("WEB_AUTH_TOKEN", "env-secret")
    raw = dict(minimal_raw)
    raw["web"] = {"auth_token": "yaml-secret"}
    assert _cfg(raw).web_auth_token() == "env-secret"


# ---- integration: the real config.yaml loads and resolves ---------------
def test_load_config_real_yaml_smoke():
    """The shipped config.yaml must load and expose sane provider defaults."""
    cfg = load_config()
    assert cfg.tts_provider_default() in {"local", "dashscope"}
    # languages() always yields at least one entry (falls back to "auto").
    assert len(cfg.languages()) >= 1
    assert cfg.sample_rate > 0
