"""Streaming WAV byte helpers — stdlib only (no numpy/torch).

Builds a WAV byte stream incrementally so synthesized audio can be sent to the
client as each chunk is produced (progressive delivery) instead of waiting for
the whole file. Kept dependency-free on purpose so it is cheap to import and
unit-testable without the heavy audio/ML stack.

A streaming WAV uses a sentinel size in its RIFF/``data`` headers: the player
reads PCM frames until the connection closes rather than trusting a length.
"""

from __future__ import annotations

import struct
from typing import Iterable, Iterator

# Max uint32 — used as the "unknown/streaming length" sentinel in the header.
_STREAM_SENTINEL = 0xFFFFFFFF


def wav_header(
    sample_rate: int,
    channels: int = 1,
    sampwidth: int = 2,
    data_size: int = _STREAM_SENTINEL,
) -> bytes:
    """Return a 44-byte PCM WAV header.

    With the default ``data_size`` (sentinel) the header describes a stream of
    unknown length; pass a real byte count to produce a normal finite header.
    """
    byte_rate = sample_rate * channels * sampwidth
    block_align = channels * sampwidth
    riff_size = _STREAM_SENTINEL if data_size == _STREAM_SENTINEL else 36 + data_size
    return (
        b"RIFF" + struct.pack("<I", riff_size) + b"WAVE"
        + b"fmt " + struct.pack(
            "<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, sampwidth * 8
        )
        + b"data" + struct.pack("<I", data_size)
    )


def clamp_pcm16(value: float) -> int:
    """Clamp a float sample in [-1, 1] to a signed 16-bit integer."""
    v = int(value * 32767)
    if v < -32768:
        return -32768
    if v > 32767:
        return 32767
    return v


def floats_to_pcm16(samples: Iterable[float]) -> bytes:
    """Convert an iterable of float samples in [-1, 1] to little-endian PCM16."""
    return b"".join(struct.pack("<h", clamp_pcm16(s)) for s in samples)


def wav_stream(
    pcm_chunks: Iterable[bytes],
    sample_rate: int,
    channels: int = 1,
    sampwidth: int = 2,
) -> Iterator[bytes]:
    """Yield a streaming WAV: the header first, then each PCM chunk in order.

    Empty chunks are skipped so callers can yield ``b""`` as a keep-alive
    without corrupting the stream.
    """
    yield wav_header(sample_rate, channels, sampwidth)
    for chunk in pcm_chunks:
        if chunk:
            yield chunk
