"""Unit tests for :mod:`voicekit.wavstream` — stdlib-only, no numpy/torch."""

from __future__ import annotations

import struct

from voicekit.wavstream import (
    clamp_pcm16,
    floats_to_pcm16,
    wav_header,
    wav_stream,
)


def test_wav_header_layout():
    h = wav_header(24000)
    assert len(h) == 44
    assert h[0:4] == b"RIFF"
    assert h[8:12] == b"WAVE"
    assert h[12:16] == b"fmt "
    assert h[36:40] == b"data"
    # Sample rate is stored little-endian at byte offset 24.
    (sample_rate,) = struct.unpack("<I", h[24:28])
    assert sample_rate == 24000


def test_wav_header_streaming_sentinel_by_default():
    h = wav_header(16000)
    (riff_size,) = struct.unpack("<I", h[4:8])
    (data_size,) = struct.unpack("<I", h[40:44])
    assert riff_size == 0xFFFFFFFF
    assert data_size == 0xFFFFFFFF


def test_wav_header_finite_size():
    h = wav_header(16000, data_size=100)
    (riff_size,) = struct.unpack("<I", h[4:8])
    (data_size,) = struct.unpack("<I", h[40:44])
    assert data_size == 100
    assert riff_size == 136  # 36 + data_size


def test_clamp_pcm16_bounds():
    assert clamp_pcm16(0.0) == 0
    assert clamp_pcm16(1.0) == 32767
    assert clamp_pcm16(-1.0) == -32767
    # Values beyond [-1, 1] are clamped to the int16 range.
    assert clamp_pcm16(2.0) == 32767
    assert clamp_pcm16(-2.0) == -32768


def test_floats_to_pcm16_roundtrip():
    raw = floats_to_pcm16([0.0, 1.0, -1.0])
    assert len(raw) == 6  # 3 samples * 2 bytes
    assert struct.unpack("<3h", raw) == (0, 32767, -32767)


def test_wav_stream_header_first_then_chunks():
    chunks = [b"\x01\x02", b"", b"\x03\x04"]
    out = list(wav_stream(chunks, 24000))
    # First item is the 44-byte header; empty chunks are skipped.
    assert out[0] == wav_header(24000)
    assert out[1:] == [b"\x01\x02", b"\x03\x04"]
