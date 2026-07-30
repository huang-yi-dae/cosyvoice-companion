"""CLI: clone a user's voice for one or more texts.

Usage:
    python internal/src/scripts/clone_voice.py [--user <qq>] [--text "..."]...
        [--reference <wav>] [--prompt-text "..."]

Defaults to ACTIVE_QQ and a small set of sample texts.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # internal/src

from voicekit import load_config
from voicekit.clone import clone_user_voice


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone a QQ user's voice via CosyVoice.")
    parser.add_argument("--user", help="QQ number (defaults to ACTIVE_QQ in .env)")
    parser.add_argument("--text", action="append", help="Text to synthesize (repeatable)")
    parser.add_argument("--reference", help="Reference WAV filename (defaults to first available)")
    parser.add_argument("--prompt-text", help="Prompt text for zero-shot cloning")
    args = parser.parse_args()

    cfg = load_config()
    result = clone_user_voice(
        cfg,
        qq=args.user,
        texts=args.text,
        reference=args.reference,
        prompt_text=args.prompt_text,
    )

    print("=" * 60)
    print(f"Cloned voice for QQ {result['qq']}")
    print("=" * 60)
    print(f"  reference : {result['reference']}")
    print(f"  generated : {result['count']} file(s)")
    for out in result["outputs"]:
        print(f"    - {out}")


if __name__ == "__main__":
    main()
