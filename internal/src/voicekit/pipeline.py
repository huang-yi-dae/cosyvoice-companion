"""End-to-end automation pipeline for the QQ -> voice/agent workflow.

Chains the individual config-driven steps into one orchestrated run with
structured progress events and per-step error handling:

    key -> decrypt -> export -> clean -> voice -> agent

Each step reports one of four statuses:
  * ``ok``      — completed successfully
  * ``error``   — failed unexpectedly (exception / tool error)
  * ``blocked`` — a manual prerequisite is missing (needs human action, then
                  resume) — e.g. not running as admin, QQ not logged in, or the
                  encrypted DB has not been copied in yet
  * ``skipped`` — not run because an earlier step stopped the pipeline

The only inherently manual step is logging in to QQ and making its encrypted
database available; everything else runs automatically. Callers pass an
``on_event`` callback to stream progress (used by both the CLI and the web
dashboard).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from .config import Config

EventFn = Callable[[dict], None]

# ---- step implementations ----------------------------------------------------
# Each returns a dict: {"status": str, "error": str|None, "detail": dict}


def _wrap(ok: bool, res: dict, blocked_hint: Optional[str] = None) -> dict:
    """Normalize a voicekit result dict into a step outcome."""
    if ok:
        return {"status": "ok", "error": None, "detail": res}
    err = res.get("error") if isinstance(res, dict) else str(res)
    status = "blocked" if blocked_hint else "error"
    return {"status": status, "error": err or blocked_hint, "detail": res if isinstance(res, dict) else {}}


def _step_key(config: Config, qq: str, ctx: dict, on_log) -> dict:
    from . import keyextract
    if config.sqlcipher_key and ctx.get("skip_if_key"):
        on_log("[key] SQLCIPHER_KEY already set — skipping extraction.")
        return {"status": "ok", "error": None, "detail": {"skipped": True}}
    if not keyextract.is_admin():
        return {
            "status": "blocked",
            "error": "Run as Administrator (SeDebugPrivilege) to extract the key, "
                     "then resume. Also make sure QQ is running and logged in.",
            "detail": {"admin": False},
        }
    res = keyextract.extract_and_store(config, on_log=on_log)
    return _wrap(bool(res.get("ok")), res)


def _step_decrypt(config: Config, qq: str, ctx: dict, on_log) -> dict:
    from . import decrypt
    src = config.encrypted_db(qq)
    if not src.exists():
        return {
            "status": "blocked",
            "error": f"Encrypted DB not found: {src}. Copy NTQQ's nt_msg.clean.db "
                     "(from the QQ data dir) to this path, then resume.",
            "detail": {"expected": str(src)},
        }
    if not config.sqlcipher_key:
        return {
            "status": "blocked",
            "error": "SQLCIPHER_KEY missing — run the key step first (as admin).",
            "detail": {},
        }
    res = decrypt.decrypt_db(config, qq=qq, on_log=on_log)
    return _wrap(bool(res.get("ok")), res)


def _step_export(config: Config, qq: str, ctx: dict, on_log) -> dict:
    from . import export_msgs
    res = export_msgs.export_chat_log(config, qq=qq, on_log=on_log)
    return _wrap(bool(res.get("ok")), res)


def _step_clean(config: Config, qq: str, ctx: dict, on_log) -> dict:
    from . import clean
    res = clean.clean_chat_log(config, qq=qq, on_log=on_log)
    return _wrap(bool(res.get("ok")), res)


def _step_voice(config: Config, qq: str, ctx: dict, on_log) -> dict:
    from . import extract
    ptt = ctx.get("ptt_dir")
    try:
        res = extract.extract_user_voices(config, qq=qq, ptt_dir=Path(ptt) if ptt else None)
        on_log(f"[voice] {res.get('converted', 0)} converted / "
               f"{res.get('voice_messages', 0)} voice messages")
        return {"status": "ok", "error": None, "detail": res}
    except FileNotFoundError as e:
        return {"status": "blocked",
                "error": f"{e}. Ensure the chat log exists and the Ptt dir is set.",
                "detail": {}}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e), "detail": {}}


def _step_agent(config: Config, qq: str, ctx: dict, on_log) -> dict:
    from . import agentgen
    res = agentgen.generate_agent(config, qq=qq, on_log=on_log)
    return _wrap(bool(res.get("ok")), res)


# ---- step registry (ordered) -------------------------------------------------
STEPS: List[dict] = [
    {"id": "key", "title": "提取解密密钥", "auto": True, "fn": _step_key,
     "description": "以管理员身份运行 PowerShell 脚本，从运行中的 QQ 进程读取 SQLCipher 密钥并写入 .env"},
    {"id": "decrypt", "title": "解密数据库", "auto": True, "fn": _step_decrypt,
     "description": "用密钥解密 NTQQ 数据库，导出明文 SQLite 文件"},
    {"id": "export", "title": "导出聊天记录", "auto": True, "fn": _step_export,
     "description": "从明文数据库导出该用户的私聊记录为 chat_log.json"},
    {"id": "clean", "title": "清洗数据", "auto": True, "fn": _step_clean,
     "description": "规则清洗解密残留、表情码、引用、重复与空/未知消息"},
    {"id": "voice", "title": "转换语音格式", "auto": True, "fn": _step_voice,
     "description": "定位该用户的 SILK 语音并转换为 WAV"},
    {"id": "agent", "title": "生成角色扮演 Agent", "auto": True, "fn": _step_agent,
     "description": "根据清洗后的记录生成 SystemPrompt 与知识库片段"},
]

STEP_IDS = [s["id"] for s in STEPS]


def pipeline_steps() -> List[dict]:
    """Return step metadata (no runners) for UIs to render the plan upfront."""
    return [{k: s[k] for k in ("id", "title", "auto", "description")} for s in STEPS]


def run_pipeline(
    config: Config,
    qq: Optional[str] = None,
    step_ids: Optional[List[str]] = None,
    *,
    on_event: Optional[EventFn] = None,
    ptt_dir: Optional[str] = None,
    stop_on_error: bool = True,
    skip_if_key: bool = True,
) -> dict:
    """Run the pipeline (optionally a subset of steps) for ``qq``.

    Returns a report ``{"ok", "qq", "steps": [...], "stopped_at": id|None}``.
    """
    qq = config.resolve_qq(qq)
    selected = step_ids or STEP_IDS
    ctx = {"ptt_dir": ptt_dir, "skip_if_key": skip_if_key}

    def emit(event: dict) -> None:
        if on_event:
            on_event(event)

    def log(msg: str) -> None:
        emit({"type": "log", "message": msg})

    report = {"ok": True, "qq": qq, "steps": [], "stopped_at": None}
    stopped = False

    for step in STEPS:
        sid = step["id"]
        if sid not in selected:
            continue
        if stopped:
            report["steps"].append({"id": sid, "title": step["title"], "status": "skipped",
                                    "error": None, "detail": {}})
            emit({"type": "step", "id": sid, "status": "skipped"})
            continue

        emit({"type": "step", "id": sid, "title": step["title"], "status": "running"})
        try:
            outcome = step["fn"](config, qq, ctx, log)
        except Exception as e:  # noqa: BLE001 — never let one step crash the run
            outcome = {"status": "error", "error": f"{type(e).__name__}: {e}", "detail": {}}

        entry = {"id": sid, "title": step["title"], **outcome}
        report["steps"].append(entry)
        emit({"type": "step", "id": sid, "status": outcome["status"],
              "error": outcome.get("error"), "detail": outcome.get("detail", {})})

        if outcome["status"] in ("error", "blocked") and stop_on_error:
            report["ok"] = False
            report["stopped_at"] = sid
            stopped = True

    emit({"type": "done", "ok": report["ok"], "stopped_at": report["stopped_at"]})
    return report
