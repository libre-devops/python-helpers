"""Write AGENTS.md from AI.md, so every AI coding assistant reads the same instructions.

    python scripts/ai_instructions.py            # write AGENTS.md
    python scripts/ai_instructions.py --check    # exit 1 when AGENTS.md is out of date

AI.md is the file people edit. Codex, Copilot's coding agent, Cursor, Gemini and most others
read AGENTS.md, which cannot import another file, so it is a copy with a note on top.
Claude Code imports AI.md from CLAUDE.md instead, and Copilot in the IDE is pointed at it
from .github/copilot-instructions.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = "<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->\n\n"


def render(root: Path = ROOT) -> str:
    """What AGENTS.md should hold: the note, then AI.md as it is."""
    return HEADER + (root / "AI.md").read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Write AGENTS.md from AI.md, or with --check say whether it is current (1 if not)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only report whether it is current")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository")
    args = parser.parse_args(argv)
    target = args.root / "AGENTS.md"
    wanted = render(args.root)
    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != wanted:
            print("AGENTS.md is out of date with AI.md: run 'just ai'", file=sys.stderr)
            return 1
        return 0
    target.write_text(wanted, encoding="utf-8", newline="\n")
    print(f"wrote {target.name} from AI.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
