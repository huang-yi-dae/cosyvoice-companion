"""Per-user voice extraction from decrypted QQ chat logs.

Generalizes the old per-user extract script: reads a user's
``chat_log.json``, finds voice messages sent by that user, locates the SILK
files under the raw Ptt directory, copies them, and converts to WAV — all
driven by :class:`Config` so any QQ works without code changes.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import List, Optional

from .audio import silk_to_wav
from .config import Config


def _find_voice_filenames(chat_log: Path, qq: str) -> List[str]:
    """Return .amr filenames from voice messages sent by ``qq``."""
    with open(chat_log, "r", encoding="utf-8") as f:
        data = json.load(f)

    filenames: List[str] = []
    for msg in data.get("messages", []):
        if str(msg.get("sender")) == str(qq) and msg.get("type") == "voice":
            content = msg.get("content", "")
            if ".amr" in content:
                filenames.append(content.split(".amr")[0] + ".amr")
    return filenames


def _locate_and_copy(ptt_dir: Path, filenames: List[str], dst_dir: Path) -> int:
    """Copy each SILK file found under ``ptt_dir`` into ``dst_dir``."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    index = {}
    for root, _dirs, files in os.walk(ptt_dir):
        for f in files:
            index.setdefault(f, os.path.join(root, f))
    for name in filenames:
        src = index.get(name)
        if src:
            shutil.copy2(src, dst_dir / name)
            copied += 1
    return copied


def extract_user_voices(
    config: Config,
    qq: Optional[str] = None,
    ptt_dir: Optional[Path] = None,
) -> dict:
    """Extract and convert voice files for ``qq`` (defaults to ACTIVE_QQ).

    ``ptt_dir`` defaults to the user's raw dir; pass an explicit path if the
    NTQQ Ptt folder lives elsewhere.
    """
    qq = config.resolve_qq(qq)
    chat_log = config.chat_log(qq)
    if not chat_log.exists():
        raise FileNotFoundError(f"chat_log not found: {chat_log}")

    silk_dir = config.user_path("voices_silk", qq, create=True)
    wav_dir = config.user_path("voices_wav", qq, create=True)
    ptt_dir = Path(ptt_dir) if ptt_dir else config.user_path("raw", qq)

    filenames = _find_voice_filenames(chat_log, qq)
    copied = _locate_and_copy(ptt_dir, filenames, silk_dir)

    converted, failed = 0, 0
    decoder = config.tool("silk_decoder")
    for silk in sorted(silk_dir.glob("*.amr")):
        wav_out = wav_dir / (silk.stem + ".wav")
        if silk_to_wav(silk, wav_out, decoder, config.sample_rate):
            converted += 1
        else:
            failed += 1

    return {
        "qq": qq,
        "voice_messages": len(filenames),
        "copied": copied,
        "converted": converted,
        "failed": failed,
        "silk_dir": str(silk_dir),
        "wav_dir": str(wav_dir),
    }
