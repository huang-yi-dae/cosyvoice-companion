"""CLI: extract the NTQQ SQLCipher key and write it to .env.

Usage (run in an **Administrator** shell, with QQ running + logged in):
    python internal/src/scripts/extract_key.py [--no-debug] [--no-write]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # internal/src

from voicekit import load_config
from voicekit import keyextract


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract the NTQQ SQLCipher key.")
    parser.add_argument("--no-debug", action="store_true",
                        help="Static analysis only (do not debug QQ; no key)")
    parser.add_argument("--no-write", action="store_true",
                        help="Print result but do not write .env")
    args = parser.parse_args()

    cfg = load_config()
    if args.no_write:
        res = keyextract.extract_key(cfg, no_debug=args.no_debug)
    else:
        res = keyextract.extract_and_store(cfg, no_debug=args.no_debug)

    if res.get("ok"):
        print(f"OK — key extracted ({len(res['key'])} chars).")
        if res.get("env_written"):
            print(f"Saved SQLCIPHER_KEY -> {res['env_written']}")
        sys.exit(0)
    print(f"FAILED: {res.get('error')}")
    sys.exit(1)


if __name__ == "__main__":
    main()
