"""Unit tests for the TTS provider abstraction and the DashScope provider.

No network is used: we only exercise construction/validation guards and the
abstract-contract properties. The ``dashscope`` package is not required because
it is imported lazily inside ``synthesize_to_file``.
"""

from __future__ import annotations

import pytest

from voicekit.tts_base import TTSProvider
from voicekit.dashscope_tts import DashScopeTTSProvider


# ---- abstract base -------------------------------------------------------
def test_ttsprovider_is_abstract():
    with pytest.raises(TypeError):
        TTSProvider()  # abstract methods not implemented


def test_ttsprovider_default_needs_reference():
    assert TTSProvider.needs_reference is True


# ---- DashScope provider construction / validation ------------------------
def test_dashscope_missing_key_raises():
    with pytest.raises(ValueError):
        DashScopeTTSProvider(api_key=None)
    with pytest.raises(ValueError):
        DashScopeTTSProvider(api_key="")


def test_dashscope_basic_attributes():
    p = DashScopeTTSProvider(api_key="sk-test", target_model="cosyvoice-v3.5-flash")
    assert p.needs_reference is False
    assert p.sample_rate == 24000
    assert p.name == "dashscope:cosyvoice-v3.5-flash"


def test_dashscope_synthesize_without_voice_raises(tmp_path):
    p = DashScopeTTSProvider(api_key="sk-test")
    with pytest.raises(ValueError):
        p.synthesize_to_file("hello", tmp_path / "out.wav", voice=None)
