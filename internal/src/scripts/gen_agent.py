"""CLI: generate a roleplay agent (SystemPrompt + knowledge base) for a user.

Usage:
    python internal/src/scripts/gen_agent.py [--user <qq>] [--name <agent>]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # internal/src

from voicekit import load_config
from voicekit import agentgen


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a roleplay agent.")
    parser.add_argument("--user", help="QQ number (defaults to ACTIVE_QQ in .env)")
    parser.add_argument("--name", help="Agent folder name (defaults to companion-<qq>)")
    args = parser.parse_args()

    cfg = load_config()
    res = agentgen.generate_agent(cfg, qq=args.user, name=args.name)
    if res.get("ok"):
        print(f"OK — agent '{res['agent']}' generated")
        print(f"     prompt: {res['prompt_chars']} chars, "
              f"{res['knowledge_files']} knowledge snippets")
        print(f"     -> {res['dir']}")
        sys.exit(0)
    print(f"FAILED: {res.get('error')}")
    sys.exit(1)


if __name__ == "__main__":
    main()
