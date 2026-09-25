"""Write AGENTS.md and Kiro's steering files from AI.md, so every assistant reads the same rules.

    python scripts/ai_instructions.py            # write them
    python scripts/ai_instructions.py --check    # exit 1 when any is out of date

AI.md is the file people edit. Codex, Copilot's coding agent, Cursor, Gemini and most others
read AGENTS.md, which cannot import another file, so it is a copy with a note on top.
Claude Code imports AI.md from CLAUDE.md instead, and Copilot in the IDE is pointed at it
from .github/copilot-instructions.md.

Kiro (and Amazon Q's successor, the Kiro CLI) reads .kiro/steering/, one file per purpose,
each loaded always or only while a file it names is open. So each section of AI.md becomes
one steering file there, as STEERING says: product.md, tech.md and structure.md are the
three Kiro expects. A section with no entry in STEERING is an error, so a new one cannot be
left out.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = "<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->\n\n"
STEERING_DIR = Path(".kiro") / "steering"
_PYTHON = ["src/**/*.py", "tests/**/*.py", "scripts/**/*.py"]
# Each section of AI.md: its steering file, and the files that load it (None: always).
STEERING: dict[str, tuple[str, list[str] | None]] = {
    "What this is": ("product.md", None),
    "Working here": ("tech.md", None),
    "Layout and layering": ("structure.md", None),
    "Names and branding": ("branding.md", None),
    "Writing code": ("code.md", _PYTHON),
    "Tests": ("tests.md", ["tests/**"]),
    "Docs": ("docs.md", ["**/*.md"]),
    # Always: an assistant must know not to commit whatever file it is in.
    "Commits and releases": ("releases.md", None),
    "Pitfalls already met": ("pitfalls.md", None),
}


def render(root: Path = ROOT) -> str:
    """What AGENTS.md should hold: the note, then AI.md as it is."""
    return HEADER + (root / "AI.md").read_text(encoding="utf-8")


def sections(text: str) -> dict[str, str]:
    """AI.md's ``##`` sections, by heading, each without its heading line. A ``##`` inside
    a code block is not a heading."""
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if line.startswith("## ") and not fenced:
            current = found.setdefault(line[3:].strip(), [])
        elif current is not None:
            current.append(line)
    return {title: "\n".join(lines).strip() + "\n" for title, lines in found.items()}


def steering(root: Path = ROOT) -> dict[str, str]:
    """Each steering file's name and content: Kiro's front matter, the note, the section."""
    parts = sections((root / "AI.md").read_text(encoding="utf-8"))
    unplaced = sorted(set(parts) - set(STEERING))
    missing = sorted(set(STEERING) - set(parts))
    if unplaced or missing:
        raise SystemExit(
            f"AI.md and STEERING in {Path(__file__).name} disagree: sections without a "
            f"steering file {unplaced}, steering files without a section {missing}"
        )
    return {
        name: _front_matter(patterns) + HEADER + f"# {title}\n\n{parts[title]}"
        for title, (name, patterns) in STEERING.items()
    }


def _front_matter(patterns: list[str] | None) -> str:
    if patterns is None:
        return "---\ninclusion: always\n---\n\n"
    listed = ", ".join(f'"{pattern}"' for pattern in patterns)
    return f"---\ninclusion: fileMatch\nfileMatchPattern: [{listed}]\n---\n\n"


def wanted(root: Path) -> dict[Path, str]:
    """Every generated file, by path, and what it should hold."""
    files = {root / "AGENTS.md": render(root)}
    files.update({root / STEERING_DIR / name: text for name, text in steering(root).items()})
    return files


def main(argv: list[str] | None = None) -> int:
    """Write the generated files from AI.md, or with --check say whether they are current."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only report whether they are current")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository")
    args = parser.parse_args(argv)
    files = wanted(args.root)
    if args.check:
        stale = [path for path, text in files.items() if _read(path) != text]
        for path in stale:
            print(
                f"{path.relative_to(args.root)} is out of date with AI.md: run 'just ai'",
                file=sys.stderr,
            )
        return 1 if stale else 0
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    where = STEERING_DIR.as_posix()
    print(f"wrote AGENTS.md and {len(files) - 1} steering files in {where} from AI.md")
    return 0


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


if __name__ == "__main__":
    sys.exit(main())
