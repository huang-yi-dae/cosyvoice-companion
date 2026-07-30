"""CLI: export a decrypted NTQQ DB to a per-user chat_log.json.

Usage:
    python internal/src/scripts/export_msgs.py [--user <qq>] [--db <path>]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # internal/src

from voicekit import load_config
from voicekit import export_msgs


def main() -> None:
    parser = argparse.ArgumentParser(description="Export chat log from a decrypted DB.")
    parser.add_argument("--user", help="QQ number (defaults to ACTIVE_QQ in .env)")
    parser.add_argument("--db", help="Path to the decrypted DB (defaults to the user's)")
    args = parser.parse_args()

    cfg = load_config()
    res = export_msgs.export_chat_log(
        cfg, decrypted_db=Path(args.db) if args.db else None, qq=args.user
    )
    if res.get("ok"):
        print(f"OK — {res['messages']} messages -> {res['out']}")
        sys.exit(0)
    print(f"FAILED: {res.get('error')}")
    sys.exit(1)


if __name__ == "__main__":
    main()
