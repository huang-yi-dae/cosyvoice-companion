"""Decrypt an NTQQ SQLCipher database to a plaintext SQLite file.

The extracted key can appear in several forms (16-char ASCII passphrase, its
hex encoding, or a longer hex blob from which a 32-char window is the real
key). This module tries each interpretation with the NTQQ cipher PRAGMAs and,
on the first that lists tables successfully, exports a decrypted copy via
``sqlcipher_export`` — the same approach the original one-off script used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from .config import Config

LogFn = Callable[[str], None]


def _emit(on_log: Optional[LogFn], msg: str) -> None:
    if on_log:
        on_log(msg)
    else:
        print(msg)


def candidate_keys(full: str) -> List[str]:
    """Yield distinct key candidates derived from the stored key string.

    Covers: the raw string as-is (ASCII passphrase), and — when it looks like a
    long hex blob — 32-char windows plus the full value.
    """
    seen = set()
    out: List[str] = []

    def add(cand: Optional[str]) -> None:
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)

    add(full)  # ASCII passphrase (most common: the 16-char key)
    is_hexish = len(full) >= 32 and all(c in "0123456789abcdefABCDEF" for c in full)
    if is_hexish:
        for cand in (full[:32], full[32:64], full[64:96], full[-32:]):
            if len(cand) == 32:
                add(cand)
    return out


def _key_pragma(key: str) -> str:
    """Return the PRAGMA key clause: raw-key form for 64-hex, else passphrase."""
    if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
        return f"PRAGMA key = \"x'{key}'\""
    if len(key) == 32 and all(c in "0123456789abcdefABCDEF" for c in key):
        # 32 hex chars = 16 bytes raw key
        return f"PRAGMA key = \"x'{key}'\""
    escaped = key.replace("'", "''")
    return f"PRAGMA key = '{escaped}'"


def _apply_pragmas(cur, key: str, pragmas: dict) -> None:
    cur.execute(_key_pragma(key))
    cur.execute(f"PRAGMA cipher_page_size = {int(pragmas['cipher_page_size'])}")
    cur.execute(f"PRAGMA kdf_iter = {int(pragmas['kdf_iter'])}")
    cur.execute(f"PRAGMA cipher_hmac_algorithm = {pragmas['cipher_hmac_algorithm']}")
    cur.execute(f"PRAGMA cipher = '{pragmas['cipher']}'")


def decrypt_db(
    config: Config,
    src_db: Optional[Path] = None,
    out_db: Optional[Path] = None,
    qq: Optional[str] = None,
    *,
    on_log: Optional[LogFn] = None,
) -> dict:
    """Decrypt ``src_db`` to ``out_db`` using the key from ``.env``.

    Defaults: ``src_db`` = the user's encrypted DB, ``out_db`` = the user's
    plaintext DB. Returns a dict describing the outcome.
    """
    qq = config.resolve_qq(qq)
    src = Path(src_db) if src_db else config.encrypted_db(qq)
    out = Path(out_db) if out_db else config.decrypted_db(qq)
    result = {"ok": False, "src": str(src), "out": str(out), "tables": 0, "error": None}

    if not config.sqlcipher_key:
        result["error"] = "SQLCIPHER_KEY is not set in .env (run the key step first)."
        return result
    if not src.exists():
        result["error"] = f"Encrypted DB not found: {src}"
        return result

    try:
        import sqlcipher3  # noqa: F401
    except ImportError:
        result["error"] = (
            "sqlcipher3 is not installed. Install it into the project venv: "
            "pip install sqlcipher3-binary"
        )
        return result
    import sqlcipher3

    pragmas = config.cipher_pragmas()
    out.parent.mkdir(parents=True, exist_ok=True)

    for i, key in enumerate(candidate_keys(config.sqlcipher_key)):
        _emit(on_log, f"[decrypt] trying key candidate {i + 1} ({len(key)} chars)")
        conn = None
        try:
            conn = sqlcipher3.connect(str(src))
            cur = conn.cursor()
            _apply_pragmas(cur, key, pragmas)
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [t[0] for t in cur.fetchall()]
            if not tables:
                conn.close()
                continue

            _emit(on_log, f"[decrypt] key works — {len(tables)} tables; exporting…")
            if out.exists():
                out.unlink()
            esc_out = str(out).replace("'", "''")
            cur.execute(f"ATTACH DATABASE '{esc_out}' AS plaintext KEY ''")
            cur.execute("SELECT sqlcipher_export('plaintext')")
            cur.execute("DETACH DATABASE plaintext")
            conn.close()

            size = out.stat().st_size if out.exists() else 0
            result.update(ok=True, tables=len(tables), size=size, table_names=tables)
            _emit(on_log, f"[decrypt] wrote {size:,} bytes -> {out}")
            return result
        except Exception as e:  # noqa: BLE001 — try the next candidate
            _emit(on_log, f"[decrypt]   candidate failed: {e}")
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    result["error"] = "No key candidate could decrypt the database."
    return result
