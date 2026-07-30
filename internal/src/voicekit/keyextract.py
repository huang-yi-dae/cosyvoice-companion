"""Extract the NTQQ SQLCipher key and persist it to ``.env``.

Wraps ``internal/windows_ntqq_get_key.ps1``. That script statically analyzes
``wrapper.node`` and then attaches a debugger to the running QQ process to read
the 16-char encryption key out of the R8 register.

Requirements (cannot be automated away):
  * Windows, and the script must run **as Administrator** (debugging another
    process needs ``SeDebugPrivilege``).
  * QQ (NTQQ) must be installed, running, and logged in to the target account.

This module only orchestrates the script, parses the key from its output, and
safely writes it to ``SQLCIPHER_KEY`` in ``.env`` (never hardcoded, never
printed in full by callers).
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .config import Config

# Marker we make the PowerShell script emit so the key is trivially parseable
# regardless of the interactive Write-Host coloring the script also prints.
_MARKER = "SQLCIPHER_KEY_RESULT="

LogFn = Callable[[str], None]


def is_admin() -> bool:
    """Return True if the current process has Administrator rights (Windows)."""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 — any failure means "assume not admin"
        return False


def _emit(on_log: Optional[LogFn], msg: str) -> None:
    if on_log:
        on_log(msg)
    else:
        print(msg)


def extract_key(
    config: Config,
    *,
    no_debug: bool = False,
    timeout: int = 600,
    on_log: Optional[LogFn] = None,
) -> dict:
    """Run the key-extraction PowerShell script and return the parsed result.

    Returns a dict: ``{"ok": bool, "key": str|None, "admin": bool,
    "returncode": int, "error": str|None}``. The key is not written to ``.env``
    here — call :func:`write_env_key` for that.
    """
    script = config.ntqq_key_script
    admin = is_admin()
    result = {"ok": False, "key": None, "admin": admin, "returncode": -1, "error": None}

    if os.name != "nt":
        result["error"] = "Key extraction only runs on Windows."
        return result
    if not script.exists():
        result["error"] = f"Key script not found: {script}"
        return result
    if not admin:
        _emit(on_log, "[warn] Not running as Administrator — debugging QQ will likely fail.")

    # Invoke the script, capture its returned object's .Key via a stable marker.
    debug_arg = "-NoDebugForKey" if no_debug else ""
    ps_command = (
        "$ErrorActionPreference='Continue'; "
        f"$r = & '{script}' {debug_arg}; "
        f"if ($r -and $r.Key) {{ Write-Output ('{_MARKER}' + $r.Key) }}"
    )
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        ps_command,
    ]

    _emit(on_log, f"[key] launching: {script.name} (admin={admin}, no_debug={no_debug})")
    key: Optional[str] = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError as e:
        result["error"] = f"powershell.exe not found: {e}"
        return result

    lines: list[str] = []
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            lines.append(line)
            if line.startswith(_MARKER):
                key = line[len(_MARKER):]
            else:
                _emit(on_log, line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        result["error"] = f"Key extraction timed out after {timeout}s."
        return result

    result["returncode"] = proc.returncode

    # Fallback: parse the Chinese "加密密钥: <key>" line if the marker is absent.
    if key is None:
        for line in lines:
            if "加密密钥" in line and ":" in line:
                key = line.split(":", 1)[1].strip()
                break

    if key:
        result["ok"] = True
        result["key"] = key
        _emit(on_log, f"[key] extracted ({len(key)} chars): {key[:2]}***{key[-2:]}")
    else:
        result["error"] = (
            "No key found. Ensure you ran as Administrator and QQ is running + "
            "logged in to the target account."
        )
    return result


def write_env_key(config: Config, key: str) -> Path:
    """Write/replace ``SQLCIPHER_KEY`` in ``.env`` without touching other lines.

    Creates ``.env`` (from ``.env.example`` if present) when missing. Returns
    the ``.env`` path written.
    """
    env_path = config.env_path
    if not env_path.exists():
        example = env_path.parent / ".env.example"
        if example.exists():
            env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            env_path.write_text("", encoding="utf-8")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_line = f"SQLCIPHER_KEY={key}"
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("SQLCIPHER_KEY=") and not stripped.startswith("#"):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path


def extract_and_store(
    config: Config,
    *,
    no_debug: bool = False,
    on_log: Optional[LogFn] = None,
) -> dict:
    """Extract the key and, on success, write it to ``.env``."""
    res = extract_key(config, no_debug=no_debug, on_log=on_log)
    if res.get("ok") and res.get("key"):
        env_path = write_env_key(config, res["key"])
        res["env_written"] = str(env_path)
        _emit(on_log, f"[key] saved SQLCIPHER_KEY -> {env_path}")
    return res
