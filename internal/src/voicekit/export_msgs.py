"""Export a decrypted NTQQ database to a per-user ``chat_log.json``.

Reads the UID<->QQ mapping and the private-message table from the plaintext DB
produced by :mod:`voicekit.decrypt`, keeps every 1:1 conversation the target QQ
took part in, and writes the merged, time-sorted log in the same schema the
rest of the project already consumes::

    {"qq", "uid", "total_messages", "sources", "messages": [
        {"time", "sender", "type", "content", "source"}]}

Message ``type`` is classified from content (``.amr`` -> voice, image URLs ->
image, common document extensions -> file, otherwise text) to stay compatible
with the extract/clean steps, since the raw numeric element type is unreliable.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .config import Config

LogFn = Callable[[str], None]

_IMAGE_HINTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", "multimedia.nt.qq")
_FILE_HINTS = (".zip", ".rar", ".7z", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
               ".ppt", ".pptx", ".txt", ".apk", ".exe")


def _emit(on_log: Optional[LogFn], msg: str) -> None:
    if on_log:
        on_log(msg)
    else:
        print(msg)


def _classify(content: str) -> str:
    c = content.lower()
    if ".amr" in c or ".silk" in c:
        return "voice"
    if any(h in c for h in _IMAGE_HINTS):
        return "image"
    if any(h in c for h in _FILE_HINTS):
        return "file"
    return "text"


def _decode_blob(blob) -> str:
    if blob is None:
        return ""
    if isinstance(blob, str):
        raw = blob
    else:
        try:
            raw = bytes(blob).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return f"[Binary: {len(blob)} bytes]"
    return "".join(ch for ch in raw if ch.isprintable() or ch in "\n\r\t")


def _load_uid_map(cur) -> dict:
    """uid -> qq (as int when possible) from nt_uid_mapping_table."""
    uid_map: dict = {}
    cur.execute("SELECT * FROM nt_uid_mapping_table")
    for row in cur.fetchall():
        uid = row[1]
        qq = row[3]
        if qq in (None, ""):
            uid_map[uid] = uid
            continue
        try:
            uid_map[uid] = int(qq)
        except (TypeError, ValueError):
            uid_map[uid] = qq
    return uid_map


def export_chat_log(
    config: Config,
    decrypted_db: Optional[Path] = None,
    qq: Optional[str] = None,
    out_path: Optional[Path] = None,
    *,
    on_log: Optional[LogFn] = None,
) -> dict:
    """Export the target user's merged private chat log to ``chat_log.json``."""
    qq = config.resolve_qq(qq)
    db = Path(decrypted_db) if decrypted_db else config.decrypted_db(qq)
    out = Path(out_path) if out_path else config.chat_log(qq)
    result = {"ok": False, "db": str(db), "out": str(out), "messages": 0, "error": None}

    if not db.exists():
        result["error"] = f"Decrypted DB not found: {db} (run the decrypt step first)."
        return result

    try:
        target_qq = int(qq)
    except (TypeError, ValueError):
        target_qq = qq

    conn = sqlite3.connect(str(db))
    try:
        cur = conn.cursor()
        uid_map = _load_uid_map(cur)
        _emit(on_log, f"[export] loaded {len(uid_map)} UID mappings")

        target_uid = None
        for uid, mapped in uid_map.items():
            if mapped == target_qq:
                target_uid = uid
                break

        cur.execute(
            'SELECT "40001","40020","40021","40050","40800","40012" '
            "FROM c2c_msg_table ORDER BY \"40050\" ASC"
        )
        rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001
        conn.close()
        result["error"] = f"Failed to read messages: {e}"
        return result
    conn.close()

    messages = []
    sources = set()
    for _msg_id, sender_uid, receiver_uid, timestamp, content_blob, _mtype in rows:
        sender_qq = uid_map.get(sender_uid, sender_uid)
        receiver_qq = uid_map.get(receiver_uid, receiver_uid)
        if target_qq not in (sender_qq, receiver_qq):
            continue

        content = _decode_blob(content_blob)
        time_str = (
            datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            if timestamp else "Unknown"
        )
        source = f"private_{sender_qq}_{receiver_qq}"
        sources.add(source)
        messages.append({
            "time": time_str,
            "sender": sender_qq,
            "type": _classify(content),
            "content": content,
            "source": source,
        })

    messages.sort(key=lambda m: m["time"])
    payload = {
        "qq": target_qq,
        "uid": target_uid,
        "total_messages": len(messages),
        "sources": sorted(sources),
        "messages": messages,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    result.update(ok=True, messages=len(messages), sources=len(sources))
    _emit(on_log, f"[export] wrote {len(messages)} messages -> {out}")
    return result
