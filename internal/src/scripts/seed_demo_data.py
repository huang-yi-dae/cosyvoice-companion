"""Seed demo data so the web UI is usable out-of-the-box (online preview).

Real pipeline data requires decrypting a QQ database + downloading a ~1.2GB
model — impossible in a shared preview. This script fabricates *self-contained*
demo data so that every page shows content immediately instead of empty states:

  - 2 demo users under private/users/<qq>/ with playable WAV samples
    (original + cloned categories) generated with the stdlib wave module
    (audible tones, not silence), so voice cards and audio players work.
  - A chat_log.json per user with voice + text messages, so the manage page's
    "voice messages" list and the statistical prompt generator have input.
  - A roleplay agent SystemPrompt.txt so the companion persona is populated.
  - A placeholder model directory containing a *.yaml marker so the model
    selector and /models page show a "ready" model (no multi-GB download).

Idempotent: safe to re-run. Only touches demo QQs (10001/10002).
Run:  python internal/src/scripts/seed_demo_data.py
"""

from __future__ import annotations

import json
import math
import struct
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "internal" / "src"))

SR = 24000
DEMO = [
    {"qq": "10001", "name": "小艺", "base": 220.0},
    {"qq": "10002", "name": "阿泽", "base": 165.0},
]


def write_tone_wav(path: Path, seconds: float, base_hz: float, seed: int) -> None:
    """Write a mono 16-bit WAV: a gentle chord with vibrato + fade, audible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(SR * seconds)
    partials = [(1.0, 0.5), (2.0, 0.2), (3.0, 0.12)]
    frames = bytearray()
    for i in range(n):
        t = i / SR
        vibrato = 1.0 + 0.006 * math.sin(2 * math.pi * 5.0 * t + seed)
        sample = 0.0
        for h, g in partials:
            sample += g * math.sin(2 * math.pi * base_hz * h * vibrato * t)
        env = min(1.0, t / 0.05, (seconds - t) / 0.08)
        val = int(max(-1.0, min(1.0, sample * env * 0.6)) * 32767)
        frames += struct.pack("<h", val)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


def seed_user(cfg, u: dict) -> dict:
    qq, name, base = u["qq"], u["name"], u["base"]
    ucfg = cfg.with_user(qq)
    wav_dir = ucfg.user_path("voices_wav", create=True)
    cloned_dir = ucfg.user_path("voices_cloned", create=True)
    dec_dir = ucfg.user_path("decrypted", create=True)

    # AMR stems must be 8+ hex chars to match app.py's AMR_RE, so that
    # voice_messages() can link each chat voice message to its decoded wav.
    stems = [f"{int(qq):04x}00{k:02x}beef" for k in range(1, 5)]
    for idx, stem in enumerate(stems):
        write_tone_wav(wav_dir / f"{stem}.wav", 1.6 + 0.3 * idx, base, idx)
    for idx in range(2):
        write_tone_wav(cloned_dir / f"cloned_demo_{idx + 1}.wav", 2.2, base * 1.02, idx + 10)

    texts = [
        "在吗", "嗯嗯", "好的", "晚点聊", "哈哈哈", "你先睡吧",
        "路上小心", "记得吃饭", "我到啦", "想你了", "在忙嘛", "早点休息",
    ]
    messages = []
    ts = 1_700_000_000
    for i, stem in enumerate(stems):
        messages.append({"type": "voice", "sender": qq, "time": str(ts + i * 60),
                         "content": f"[语音]{stem}.amr"})
    messages.append({"type": "voice", "sender": qq, "time": str(ts + 999),
                     "content": "[语音]deadbeef99.amr"})
    for i, txt in enumerate(texts):
        messages.append({"type": "text", "sender": qq, "time": str(ts + 1000 + i * 30),
                         "content": txt})
        messages.append({"type": "text", "sender": "self", "time": str(ts + 1015 + i * 30),
                         "content": "嗯" if i % 2 else "好"})
    (dec_dir / cfg.chat_log_name).write_text(
        json.dumps({"messages": messages}, ensure_ascii=False, indent=2), encoding="utf-8")

    agent_dir = cfg.agents_root / cfg.agent_name(qq)
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "SystemPrompt.txt").write_text(
        "你现在要扮演一个人。你不是 AI，你就是这个人。\n\n"
        f"## 你是谁\n你叫{name}，正在和一个你在意的人聊天。\n\n"
        "## 语言风格\n- 回复极简、口语化，多为短句。\n- 语气克制、温和。\n"
        "- 常用短语：在吗、嗯嗯、好的、路上小心、早点休息。\n\n"
        "## 严格遵守的规则\n1. 回复简短，不长篇大论。\n2. 保持一致的温和语气。\n"
        "3. 不寒暄客套。\n\n（演示数据，可在管理页重新生成或微调。）\n",
        encoding="utf-8")
    return {"qq": qq, "wav": len(stems), "cloned": 2, "texts": len(texts)}


def seed_model_placeholder(cfg) -> str:
    model_dir = cfg.model_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    marker = model_dir / "cosyvoice.yaml"
    if not marker.exists():
        marker.write_text(
            "# DEMO placeholder so the model selector shows this model as ready.\n"
            "# Real synthesis requires downloading the full weights via /models.\n"
            "demo_placeholder: true\n", encoding="utf-8")
    return model_dir.name


def main() -> None:
    from voicekit import load_config

    cfg = load_config()
    print(f"private_root = {cfg.private_root}")
    results = [seed_user(cfg, u) for u in DEMO]
    model_name = seed_model_placeholder(cfg)
    print("seeded users:")
    for r in results:
        print(f"  - QQ {r['qq']}: {r['wav']} original + {r['cloned']} cloned, {r['texts']} texts")
    print(f"model placeholder: {model_name}")
    print("done.")


if __name__ == "__main__":
    main()
