"""Audio helpers: WAV loading for CosyVoice and SILK->WAV conversion.

``load_wav_fixed`` replaces CosyVoice's ``load_wav`` (which historically was
patched inline in 5+ scripts) with a single implementation returning a
[1, num_samples] tensor. ``silk_to_wav`` wraps the silk_v3_decoder.exe pipeline.
"""

from __future__ import annotations

import os
import subprocess
import wave
from pathlib import Path
from typing import Union

import numpy as np

PathLike = Union[str, os.PathLike]


def load_wav_fixed(wav: PathLike, target_sr: int, min_sr: int = 16000):
    """Load an audio file and return a torch tensor of shape [1, num_samples].

    Mono-izes multi-channel input and resamples to ``target_sr`` if needed.
    Imports of heavy deps are local so this module stays cheap to import.
    """
    import soundfile as sf
    from scipy import signal as sig
    import torch

    speech, sr = sf.read(wav)
    if speech.dtype != np.float32:
        speech = speech.astype(np.float32)
    if len(speech.shape) > 1:
        speech = speech[:, 0]

    if sr != target_sr:
        assert sr >= min_sr, f"wav sample rate {sr} must be greater than {target_sr}"
        num_samples = int(len(speech) * target_sr / sr)
        speech = sig.resample(speech, num_samples)

    return torch.from_numpy(speech).unsqueeze(0)


def concat_wavs(
    wav_paths,
    out_path: PathLike,
    target_sr: int = 16000,
    gap_ms: int = 200,
) -> Path:
    """Concatenate several WAV files into one mono ``target_sr`` file.

    Used to build a richer reference clip from multiple selected voice
    samples. Each source is mono-ized and resampled to ``target_sr``; a short
    silence gap is inserted between clips. Returns the output path.
    """
    import soundfile as sf
    from scipy import signal as sig

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(int(target_sr * gap_ms / 1000), dtype=np.float32)

    chunks = []
    for i, p in enumerate(wav_paths):
        speech, sr = sf.read(str(p))
        if speech.dtype != np.float32:
            speech = speech.astype(np.float32)
        if len(speech.shape) > 1:
            speech = speech[:, 0]
        if sr != target_sr:
            speech = sig.resample(speech, int(len(speech) * target_sr / sr)).astype(np.float32)
        if i > 0:
            chunks.append(gap)
        chunks.append(speech)

    combined = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    sf.write(str(out_path), combined, target_sr)
    return out_path


def silk_to_wav(
    silk_path: PathLike,
    wav_path: PathLike,
    decoder: PathLike,
    sample_rate: int = 24000,
    timeout: int = 30,
) -> bool:
    """Decode a SILK/AMR voice file to WAV via silk_v3_decoder.exe.

    Returns True on success. Produces a temporary .pcm alongside ``wav_path``
    which is removed afterwards.
    """
    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    pcm_path = wav_path.with_suffix(".pcm")

    cmd = [
        str(decoder),
        str(silk_path),
        str(pcm_path),
        "-Fs_API",
        str(sample_rate),
        "-quiet",
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if not (pcm_path.exists() and pcm_path.stat().st_size > 0):
        return False

    with open(pcm_path, "rb") as f:
        pcm_data = f.read()

    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_data)

    pcm_path.unlink(missing_ok=True)
    return True
