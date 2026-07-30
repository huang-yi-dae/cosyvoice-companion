"""CLI: decrypt an NTQQ SQLCipher database using the key from .env.

Usage:
    python internal/src/scripts/decrypt_db.py --db <path> [--user <qq>]

The SQLCipher key is read from SQLCIPHER_KEY in .env (never hardcoded). The full
hex value may be longer than 32 chars; this tool tries candidate 32-char
substrings, matching the original behavior.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # internal/src

from voicekit import load_config


def candidate_keys(full_hex: str):
    """Yield candidate 32-char keys derived from the full hex string."""
    seen = set()
    for cand in (full_hex[:32], full_hex[32:64], full_hex[64:96], full_hex[-32:], full_hex):
        if len(cand) == 32 and cand not in seen:
            seen.add(cand)
            yield cand


def main() -> None:
    parser = argparse.ArgumentParser(description="Decrypt an NTQQ SQLCipher DB.")
    parser.add_argument("--db", required=True, help="Path to the .clean.db file")
    parser.add_argument("--user", help="QQ number (for context/logging only)")
    args = parser.parse_args()

    cfg = load_config()
    if not cfg.sqlcipher_key:
        raise SystemExit("SQLCIPHER_KEY is not set in .env")

    import sqlcipher3

    db_path = str(Path(args.db))
    for i, key in enumerate(candidate_keys(cfg.sqlcipher_key)):
        print(f"Trying key {i}: {key[:8]}...")
        try:
            conn = sqlcipher3.connect(db_path)
            cur = conn.cursor()
            cur.execute(f"PRAGMA key = '{key}'")
            cur.execute("PRAGMA cipher_page_size = 4096")
            cur.execute("PRAGMA kdf_iter = 4000")
            cur.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1")
            cur.execute("PRAGMA cipher = 'aes-256-cbc'")
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cur.fetchall()
            print(f"SUCCESS! Tables: {[t[0] for t in tables]}")
            conn.close()
            return
        except Exception as e:  # noqa: BLE001 — report and try next key
            print(f"  failed: {e}")

    print("No candidate key worked.")


if __name__ == "__main__":
    main()
