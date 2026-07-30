"""Shared pytest fixtures and path setup for the voicekit test suite.

The ``voicekit`` package lives under ``internal/src`` (not an installed
package), so we prepend that directory to ``sys.path`` before any test imports
it. Tests here are deliberately pure-logic: no GPU, no network, no real models.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Repo root = this file's parent's parent (tests/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "internal" / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def minimal_raw() -> dict:
    """A minimal ``config.yaml``-shaped dict for isolated Config unit tests."""
    return {
        "paths": {
            "private_root": "private",
            "cosyvoice_repo": "internal/src/CosyVoice",
            "model_dir": "internal/src/CosyVoice/pretrained_models/CosyVoice-300M",
            "user_subdirs": {
                "decrypted": "users/{qq}/decrypted",
                "voices_wav": "users/{qq}/voices/wav",
                "voices_cloned": "users/{qq}/voices/cloned",
            },
        },
        "audio": {"sample_rate": 22050, "target_sr": 24000},
        "tts": {
            "provider": "local",
            "default_prompt_text": "hello",
            "providers": {
                "dashscope": {
                    "target_model": "cosyvoice-v3.5-flash",
                    "voices": [
                        {"id": "voice-abc", "label": "他的声音"},
                        {"label": "缺少 id 应被过滤"},
                    ],
                },
            },
            "languages": [
                {"code": "auto", "tag": "", "label": "自动"},
                {"code": "zh", "tag": "<|zh|>", "label": "中文"},
                {"code": "en", "tag": "<|en|>", "label": "英文"},
            ],
        },
        "models": {
            "catalog": [
                {"name": "CosyVoice-300M", "clone_ready": True},
                {"name": "CosyVoice-300M-SFT", "clone_ready": False},
            ],
        },
    }
