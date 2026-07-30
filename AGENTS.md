# AGENTS.md

This file provides guidance to the AI agent when working with code in this repository.

## Overview

Personal research project: QQ chat log analysis + voice cloning using CosyVoice-300M.
Windows-only (PowerShell). Python 3.11. Config-driven with strict privacy separation.

## Python Environment

All scripts must use the project venv, not system Python:
```
internal/env/voice-clone-env/Scripts/python.exe <script>
```

## Configuration & Privacy (READ FIRST)

- `config/config.yaml` — non-sensitive defaults (paths, model dir, sample rates). Committed.
- `.env` — sensitive values: `ACTIVE_QQ`, `SQLCIPHER_KEY`, `USER_NAME`, `PARTNER_NAME`.
  Gitignored. Copy from `.env.example`.
- `private/` — ALL privacy data (decrypted DBs, chat logs, voices, reports, agent
  knowledge bases). Entirely gitignored. NEVER commit anything under here.
- Never hardcode QQ numbers, names, keys, or absolute paths in committed code. Read
  them from `voicekit.config.load_config()`.

## Code Layout

- `internal/src/voicekit/` — shared package. Import via `from voicekit import load_config`.
  - `config.py` resolves per-user paths from templates (`ACTIVE_QQ` or `--user`).
  - `audio.py` (load_wav_fixed, silk_to_wav), `cosyvoice_engine.py`, `extract.py`, `clone.py`.
- `internal/src/scripts/` — thin CLI entrypoints, all accept `--user <qq>`.
- `internal/src/web/app.py` — FastAPI app, config-driven.
- `internal/src/tools/` — binaries only (silk_v3_decoder.exe, lame.exe, silk2mp3.exe).
- `internal/src/CosyVoice/` — vendored repo; `pretrained_models/` is gitignored.
- `internal/src/_legacy/` — archived old scripts, gitignored. Do not extend these.

## Multi-user

To analyze/clone a different QQ: create `private/users/<qq>/{decrypted,raw}/`, place that
user's `chat_log.json` and raw Ptt data, then set `ACTIVE_QQ` in `.env` or pass `--user <qq>`.
No code changes required.

## Voice Format Pipeline

QQ voice messages are SILK v3:
1. `.silk`/`.amr` -> `.wav` via `internal/src/tools/silk_v3_decoder.exe`
2. `.wav` -> cloned voice via CosyVoice (`voicekit.cosyvoice_engine`)

## Web App

```
internal/env/voice-clone-env/Scripts/python.exe internal/src/web/app.py
```
Serves FastAPI on the host/port from `config/config.yaml`. Frontend is a single `index.html`.

## Notes

- All UI text and reports are in Chinese.
- No tests, no lint config, no build system — scripts are run directly.
- `internal/env/` contains a ~large venv; do not delete or recreate it.
- PowerShell: use `;` not `&&` as a statement separator.
