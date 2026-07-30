"""Per-user voice cloning driven by :class:`Config`.

Generalizes the old per-user clone script: picks a reference WAV from the
user's converted voices and synthesizes given texts in that voice using
:class:`CosyVoiceEngine`, writing results to the user's cloned dir.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .config import Config
from .cosyvoice_engine import CosyVoiceEngine

DEFAULT_TEXTS = [
    "你好，最近怎么样？",
    "今天天气真好啊，我们一起出去走走吧。",
    "这个周末有什么计划吗？",
]


def _pick_reference(wav_dir: Path, reference: Optional[str]) -> Path:
    """Return the reference WAV: explicit name, or the first available file."""
    if reference:
        ref = wav_dir / reference if not Path(reference).is_absolute() else Path(reference)
        if not ref.exists():
            raise FileNotFoundError(f"reference wav not found: {ref}")
        return ref
    candidates = sorted(wav_dir.glob("*.wav"))
    if not candidates:
        raise FileNotFoundError(f"no WAV files found in {wav_dir}")
    return candidates[0]


def clone_user_voice(
    config: Config,
    qq: Optional[str] = None,
    texts: Optional[List[str]] = None,
    reference: Optional[str] = None,
    prompt_text: Optional[str] = None,
    engine: Optional[CosyVoiceEngine] = None,
) -> dict:
    """Clone ``texts`` in the voice of ``qq`` (defaults to ACTIVE_QQ)."""
    qq = config.resolve_qq(qq)
    texts = texts or DEFAULT_TEXTS

    wav_dir = config.user_path("voices_wav", qq)
    out_dir = config.user_path("voices_cloned", qq, create=True)
    ref_wav = _pick_reference(wav_dir, reference)

    engine = engine or CosyVoiceEngine(config)

    outputs = []
    for i, text in enumerate(texts):
        out_file = out_dir / f"cloned_{ref_wav.stem}_{i}.wav"
        engine.clone_to_file(text, ref_wav, out_file, prompt_text)
        outputs.append(str(out_file))

    return {
        "qq": qq,
        "reference": str(ref_wav),
        "count": len(outputs),
        "outputs": outputs,
        "output_dir": str(out_dir),
    }
