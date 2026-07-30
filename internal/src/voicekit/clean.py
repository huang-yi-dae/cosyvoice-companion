"""Config-driven cleaning of a decrypted QQ chat log.

This is a generalization of the original one-off ``clean_data.py``: it operates
on a single user's ``chat_log.json`` resolved through :class:`Config` (no
hardcoded QQ numbers or absolute paths) and writes ``chat_log_clean.json`` next
to it. The cleaning rules — decryption-prefix garbage, QQ emoji codes, quote
formatting, per-type normalization, dedupe, and unknown/empty filtering — are
ported verbatim so results match the previous manual pass.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from .config import Config

LogFn = Callable[[str], None]

# 1. Prefix garbage: 1-2 special chars (+ optional letter suffix) left over from
#    NTQQ decryption, or Unicode replacement chars, at the start of a message.
PREFIX_GARBAGE = re.compile(
    r"^[!'\"#\$%&\(\)\*\+,\-\.\/:;<=>?@\[\\\]\^_`\{\}\|~]{1,2}"
    r"[gGjJkKlLmMnNoOpPqQrRsStTuUvVwWxXyYzZ]{0,2}"
    r"|^[gGjJkKlLmMnNoOpPqQrRsStTuUvVwWxXyYzZ]{1,2}"
    r"|^[\ufffd\uFFFD\uFFFD]+"
)

# 2. Quote formatting: long u_xxx user IDs followed by content.
QUOTE_PATTERN = re.compile(r"u_[A-Za-z0-9_-]{20,}(?::[^u]*)?")

# 3. QQ emoji codes: $g/吃糖, 'g/划龙舟, *g/我想开了 …
QQ_EMOJI_PATTERN = re.compile(
    r"[$'*&]?g/[^\s\u4e00-\u9fff]{0,3}"
    r"|[$]?g/[^\s]{0,10}"
)

# 4. Quoted emoji: hex_hash'[emoji_name]…
QUOTED_EMOJI_PATTERN = re.compile(
    r"[a-f0-9]{10,}\['[^\]]+'\]"
    r"|[a-f0-9]{10,}'"
    r"|[a-f0-9]{10,}\["
)

# 5. File-message garbage (filename followed by a UUID-ish suffix).
FILE_GARBAGE_PATTERN = re.compile(
    r"([^\s]+\.(docx?|xlsx?|pptx?|pdf|zip|rar|txt))"
    r"[A-Za-z0-9_\-;:,.=/\+]{20,}"
)


def _emit(on_log: Optional[LogFn], msg: str) -> None:
    if on_log:
        on_log(msg)
    else:
        print(msg)


def clean_text_content(content) -> str:
    if not content:
        return ""
    text = str(content)
    original = text

    text = FILE_GARBAGE_PATTERN.sub(r"\1", text)
    text = QUOTE_PATTERN.sub("", text).strip()
    text = QUOTED_EMOJI_PATTERN.sub("", text).strip()
    text = QQ_EMOJI_PATTERN.sub("", text).strip()
    text = PREFIX_GARBAGE.sub("", text).strip()
    text = re.sub(r"[!'\"#\$%&\(\)\*\+,\-\.\/:;<=>?@\[\\\]\^_`\{\}\|~]{3,}", "", text).strip()
    text = re.sub(r"[gGjJkKlLmMnNoOpPqQrRsStTuUvVwWxXyYzZ]{1}[\d]{0,3}$", "", text).strip()
    text = re.sub(r"^[!'\"#\$%&\(\)\*\+,\-\.\/:;<=>?@\[\\\]\^_`\{\}\|~]$", "", text).strip()

    if not text and original:
        m = re.search(r"\[([^\[\]]+)\]", original)
        if m:
            text = f"[{m.group(1)}]"
    return text


def clean_image_content(content) -> str:
    text = str(content)
    m = re.search(r"([A-F0-9]{16,})\.(jpg|png|gif|bmp|jpeg)", text, re.IGNORECASE)
    if m:
        return f"[图片 {m.group(1)[:8]}.{m.group(2)}]"
    return "[图片]"


def clean_emoji_content(content) -> str:
    text = str(content)
    m = re.search(r"\[([^\[\]]+)\]", text)
    if m:
        return f"[{m.group(1)}]"
    return "[表情]"


def clean_file_content(content) -> str:
    text = str(content)
    m = re.search(r"([^\s]+\.(docx?|xlsx?|pptx?|pdf|zip|rar|txt))", text, re.IGNORECASE)
    if m:
        return f"[文件 {m.group(1)}]"
    return "[文件]"


def clean_message(msg: dict) -> dict:
    msg = dict(msg)
    content = msg.get("content", "")
    mtype = str(msg.get("type", "")).lower()

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif item.get("type") == "face":
                    texts.append(f'[{item.get("desc", "表情")}]')
            elif isinstance(item, str):
                texts.append(item)
        content = " ".join(texts)
        msg["type"] = "text"

    content = str(content)

    if mtype in ("image", "photo", "picture"):
        msg["content"] = clean_image_content(content)
        msg["type"] = "image"
    elif mtype in ("emoji", "sticker"):
        msg["content"] = clean_emoji_content(content)
        msg["type"] = "emoji"
    elif mtype in ("file",):
        msg["content"] = clean_file_content(content)
    elif mtype in ("voice", "audio", "video"):
        msg["content"] = f"[{mtype}]"
    elif mtype == "text" or mtype == "":
        cleaned = clean_text_content(content)
        if not cleaned:
            if re.search(r"\.(jpg|png|gif|jpeg)", content, re.IGNORECASE):
                msg["content"] = clean_image_content(content)
                msg["type"] = "image"
            elif re.search(r"[A-F0-9]{16,}", content) and len(content) > 100:
                msg["content"] = "[未知内容]"
                msg["type"] = "unknown"
            else:
                msg["content"] = "[空消息]"
                msg["type"] = "empty"
        else:
            msg["content"] = cleaned

    sender = msg.get("sender")
    if sender is None or str(sender) in ("None", "null", "?", ""):
        msg["sender"] = "unknown"
    return msg


def deduplicate(messages: list) -> list:
    if not messages:
        return []
    result = [messages[0]]
    for msg in messages[1:]:
        prev = result[-1]
        if (str(msg.get("content", "")) == str(prev.get("content", ""))
                and str(msg.get("sender", "")) == str(prev.get("sender", ""))
                and str(msg.get("type", "")) == str(prev.get("type", ""))):
            continue
        result.append(msg)
    return result


def clean_chat_log(
    config: Config,
    qq: Optional[str] = None,
    in_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    *,
    on_log: Optional[LogFn] = None,
) -> dict:
    """Clean a user's chat log and write ``chat_log_clean.json``.

    Reads the user's ``chat_log.json`` (or ``in_path``) and writes the cleaned
    result to ``out_path`` (defaults to the user's ``chat_log_clean.json``).
    """
    qq = config.resolve_qq(qq)
    src = Path(in_path) if in_path else (config.find_chat_log(qq) or config.chat_log(qq))
    out = Path(out_path) if out_path else config.clean_log(qq)
    result = {"ok": False, "in": str(src), "out": str(out), "error": None}

    if not src.exists():
        result["error"] = f"chat_log not found: {src} (run the export step first)."
        return result

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    msgs = data.get("messages", [])
    original_count = len(msgs)
    cleaned = [clean_message(m) for m in msgs]
    deduped = deduplicate(cleaned)
    final = [m for m in deduped if m.get("type") not in ("unknown", "empty")]
    type_counter = Counter(m.get("type") for m in final)

    meta = {
        "original_count": original_count,
        "after_clean": len(final),
        "removed_duplicates": original_count - len(deduped),
        "removed_garbage": len(deduped) - len(final),
        "type_distribution": dict(type_counter),
    }
    payload = {"qq": qq, "messages": final, "_meta": meta}

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _emit(on_log, f"[clean] {original_count} -> {len(final)} messages "
                  f"(-{meta['removed_duplicates']} dup, -{meta['removed_garbage']} garbage)")
    result.update(ok=True, **meta)
    return result
