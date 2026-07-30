"""CLI: clean a user's chat_log.json into chat_log_clean.json.

Usage:
    python internal/src/scripts/clean_chat.py [--user <qq>]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # internal/src

from voicekit import load_config
from voicekit import clean


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean a decrypted chat log.")
    parser.add_argument("--user", help="QQ number (defaults to ACTIVE_QQ in .env)")
    args = parser.parse_args()

    cfg = load_config()
    res = clean.clean_chat_log(cfg, qq=args.user)
    if res.get("ok"):
        print(f"OK — {res['original_count']} -> {res['after_clean']} messages")
        print(f"     removed {res['removed_duplicates']} duplicates, "
              f"{res['removed_garbage']} garbage/empty")
        print(f"     -> {res['out']}")
        sys.exit(0)
    print(f"FAILED: {res.get('error')}")
    sys.exit(1)


if __name__ == "__main__":
    main()
