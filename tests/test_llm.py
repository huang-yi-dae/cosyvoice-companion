"""Unit tests for :mod:`voicekit.llm` — pure logic, no dashscope/network.

Only message assembly, history trimming, construction guards and the response
parser are exercised; the ``dashscope`` SDK is imported lazily inside ``chat``.
"""

from __future__ import annotations

import pytest

from voicekit.llm import (
    DEFAULT_MODEL,
    LLMClient,
    build_messages,
    trim_history,
    _extract_reply,
)


# ---- trim_history --------------------------------------------------------
def test_trim_history_keeps_last_pairs():
    history = [{"role": "user", "content": str(i)} for i in range(10)]
    out = trim_history(history, max_turns=2)
    assert len(out) == 4  # 2 pairs = 4 messages
    assert out[0]["content"] == "6"
    assert out[-1]["content"] == "9"


def test_trim_history_drops_invalid_entries():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "ignored"},  # bad role
        {"role": "assistant", "content": "  "},      # empty
        {"role": "assistant", "content": "hello"},
    ]
    out = trim_history(history, max_turns=6)
    assert out == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_trim_history_empty_or_zero():
    assert trim_history(None, 6) == []
    assert trim_history([{"role": "user", "content": "x"}], 0) == []


# ---- build_messages ------------------------------------------------------
def test_build_messages_structure():
    msgs = build_messages("PERSONA", [{"role": "user", "content": "a"}], "b", max_turns=6)
    assert msgs[0] == {"role": "system", "content": "PERSONA"}
    assert msgs[-1] == {"role": "user", "content": "b"}
    assert {"role": "user", "content": "a"} in msgs


def test_build_messages_omits_blank_system():
    msgs = build_messages("   ", None, "hi")
    assert msgs == [{"role": "user", "content": "hi"}]


# ---- LLMClient construction ---------------------------------------------
def test_llmclient_missing_key_raises():
    with pytest.raises(ValueError):
        LLMClient(api_key=None)
    with pytest.raises(ValueError):
        LLMClient(api_key="")


def test_llmclient_defaults_and_name():
    c = LLMClient(api_key="sk-test")
    assert c.model == DEFAULT_MODEL
    assert c.name == f"dashscope:{DEFAULT_MODEL}"
    assert c.max_turns == 6


def test_llmclient_chat_empty_message_raises():
    c = LLMClient(api_key="sk-test")
    with pytest.raises(ValueError):
        c.chat("persona", [], "   ")


# ---- _extract_reply ------------------------------------------------------
class _Resp:
    def __init__(self, status_code=200, output=None, message=""):
        self.status_code = status_code
        self.output = output
        self.message = message


def test_extract_reply_message_format():
    resp = _Resp(output={"choices": [{"message": {"content": " hi "}}]})
    assert _extract_reply(resp) == "hi"


def test_extract_reply_text_fallback():
    resp = _Resp(output={"text": " hello "})
    assert _extract_reply(resp) == "hello"


def test_extract_reply_non_200_raises():
    resp = _Resp(status_code=401, message="bad key")
    with pytest.raises(RuntimeError):
        _extract_reply(resp)
