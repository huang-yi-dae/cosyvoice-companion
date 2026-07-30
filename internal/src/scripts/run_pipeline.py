"""CLI: run the full QQ -> voice/agent automation pipeline.

Usage:
    python internal/src/scripts/run_pipeline.py [--user <qq>] [--steps a,b,c]
        [--ptt-dir <path>] [--continue-on-error]

Steps: key, decrypt, export, clean, voice, agent (default: all, in order).
Only "logging in to QQ + copying its encrypted DB" is manual; a step that needs
manual action reports status ``blocked`` with instructions so you can fix it and
re-run. Must be run **as Administrator** for the key step to work.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # internal/src

from voicekit import load_config
from voicekit import pipeline


def _on_event(event: dict) -> None:
    etype = event.get("type")
    if etype == "log":
        print("   ", event.get("message", ""))
    elif etype == "step":
        status = event.get("status")
        if status == "running":
            print(f"\n>>> {event.get('title', event.get('id'))} …")
        else:
            icon = {"ok": "[OK]", "blocked": "[MANUAL]", "error": "[FAIL]",
                    "skipped": "[SKIP]"}.get(status, status)
            line = f"    {icon} {event.get('id')}"
            if event.get("error"):
                line += f" — {event['error']}"
            print(line)
    elif etype == "done":
        print("\n" + ("Pipeline complete." if event.get("ok")
                       else f"Pipeline stopped at: {event.get('stopped_at')}"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the QQ automation pipeline.")
    parser.add_argument("--user", help="QQ number (defaults to ACTIVE_QQ in .env)")
    parser.add_argument("--steps", help=f"Comma-separated subset of: {','.join(pipeline.STEP_IDS)}")
    parser.add_argument("--ptt-dir", help="NTQQ Ptt directory for voice extraction")
    parser.add_argument("--continue-on-error", action="store_true",
                        help="Keep running subsequent steps even if one fails")
    args = parser.parse_args()

    cfg = load_config()
    step_ids = [s.strip() for s in args.steps.split(",")] if args.steps else None
    if step_ids:
        bad = [s for s in step_ids if s not in pipeline.STEP_IDS]
        if bad:
            raise SystemExit(f"Unknown step(s): {bad}. Valid: {pipeline.STEP_IDS}")

    report = pipeline.run_pipeline(
        cfg,
        qq=args.user,
        step_ids=step_ids,
        on_event=_on_event,
        ptt_dir=args.ptt_dir,
        stop_on_error=not args.continue_on_error,
    )
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
