"""CLI: batch-convert SILK/AMR files to WAV for a user.

Usage:
    python internal/src/scripts/convert_silk.py [--user <qq>] [--limit N]

Reads from the user's voices/silk dir, writes to voices/wav.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # internal/src

from voicekit import load_config
from voicekit.audio import silk_to_wav


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch convert SILK to WAV.")
    parser.add_argument("--user", help="QQ number (defaults to ACTIVE_QQ in .env)")
    parser.add_argument("--limit", type=int, default=0, help="Convert at most N files (0 = all)")
    args = parser.parse_args()

    cfg = load_config()
    silk_dir = cfg.user_path("voices_silk", args.user)
    wav_dir = cfg.user_path("voices_wav", args.user, create=True)
    decoder = cfg.tool("silk_decoder")

    silk_files = sorted(silk_dir.glob("*.amr"))
    if args.limit:
        silk_files = silk_files[: args.limit]

    print(f"Converting {len(silk_files)} SILK files from {silk_dir}")
    converted, failed = 0, 0
    for i, silk in enumerate(silk_files, 1):
        wav_out = wav_dir / (silk.stem + ".wav")
        ok = silk_to_wav(silk, wav_out, decoder, cfg.sample_rate)
        print(f"  [{i}/{len(silk_files)}] {silk.name} -> {'OK' if ok else 'FAILED'}")
        converted += int(ok)
        failed += int(not ok)

    print(f"Done. converted={converted} failed={failed} -> {wav_dir}")


if __name__ == "__main__":
    main()
