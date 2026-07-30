"""Unit tests for :mod:`voicekit.clean` — chat-log cleaning pure logic."""

from __future__ import annotations

from voicekit.clean import (
    clean_emoji_content,
    clean_file_content,
    clean_image_content,
    clean_message,
    deduplicate,
)


def test_clean_image_content_extracts_hash():
    out = clean_image_content("ABCDEF0123456789ABCD.jpg")
    assert out == "[图片 ABCDEF01.jpg]"


def test_clean_image_content_fallback():
    assert clean_image_content("no hash here") == "[图片]"


def test_clean_emoji_content_keeps_bracket_name():
    assert clean_emoji_content("prefix[微笑]suffix") == "[微笑]"
    assert clean_emoji_content("nothing") == "[表情]"


def test_clean_file_content_extracts_filename():
    assert clean_file_content("报告.docx随后一串垃圾").startswith("[文件 报告.docx")
    assert clean_file_content("no file") == "[文件]"


def test_clean_message_normalizes_missing_sender():
    msg = clean_message({"type": "text", "content": "你好", "sender": None})
    assert msg["sender"] == "unknown"
    assert msg["content"] == "你好"


def test_clean_message_empty_text_becomes_placeholder():
    msg = clean_message({"type": "text", "content": "", "sender": "a"})
    assert msg["type"] == "empty"
    assert msg["content"] == "[空消息]"


def test_clean_message_list_content_joined_to_text():
    msg = clean_message({
        "type": "text",
        "sender": "a",
        "content": [
            {"type": "text", "text": "在吗"},
            {"type": "face", "desc": "微笑"},
        ],
    })
    assert msg["type"] == "text"
    assert "在吗" in msg["content"]
    assert "[微笑]" in msg["content"]


def test_clean_message_image_type():
    msg = clean_message({"type": "image", "content": "ABCDEF0123456789ABCD.png", "sender": "a"})
    assert msg["type"] == "image"
    assert msg["content"].startswith("[图片 ")


def test_deduplicate_removes_consecutive_identical():
    msgs = [
        {"content": "hi", "sender": "a", "type": "text"},
        {"content": "hi", "sender": "a", "type": "text"},
        {"content": "hi", "sender": "b", "type": "text"},
        {"content": "bye", "sender": "b", "type": "text"},
    ]
    out = deduplicate(msgs)
    # Only the first duplicate (same content/sender/type) is dropped.
    assert len(out) == 3
    assert out[0]["content"] == "hi" and out[0]["sender"] == "a"
    assert out[1]["sender"] == "b"
    assert out[2]["content"] == "bye"


def test_deduplicate_empty():
    assert deduplicate([]) == []
