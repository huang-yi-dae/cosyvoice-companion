"""CLI: extract and convert a user's voice messages.

Usage:
    python internal/src/scripts/extract_voice.py [--user <qq>] [--ptt-dir <path>]

Defaults to ACTIVE_QQ from .env. No business logic here — delegates to voicekit.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # internal/src

from voicekit import load_config
from voicekit.extract import extract_user_voices


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and convert QQ voice messages.")
    parser.add_argument("--user", help="QQ number (defaults to ACTIVE_QQ in .env)")
    parser.add_argument("--ptt-dir", help="Override raw NTQQ Ptt directory")
    args = parser.parse_args()

    cfg = load_config()
    result = extract_user_voices(cfg, qq=args.user, ptt_dir=args.ptt_dir)

    print("=" * 60)
    print(f"Extracted voices for QQ {result['qq']}")
    print("=" * 60)
    print(f"  voice messages : {result['voice_messages']}")
    print(f"  copied SILK    : {result['copied']}")
    print(f"  converted WAV  : {result['converted']} (failed: {result['failed']})")
    print(f"  wav dir        : {result['wav_dir']}")


if __name__ == "__main__":
    main()
