"""Rename this project: its command, package, distribution, env prefix and error class.

For shipping the code under another organisation's name, for example inside a company:

    just rebrand --command contoso --display-name "Contoso Helpers"
    just rebrand --command acme --package acme_tools --repository https://git.acme.test/tools
    just rebrand --command acme --banner acme-logo.txt     # or --no-banner

Every name is a parameter; anything not given keeps its current value, and some follow
from others (the env prefix and error class from the command, the distribution from
the package). The current names are read from brand.toml, so the rename can be run again
later. LICENSE is never touched: the MIT licence requires its copyright and permission
notice to stay with the code.

After rewriting, the lock file is refreshed and the checks run, unless --no-verify.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

# Never rewritten: the licence must keep its notice, the lock file is regenerated, and
# this script holds no names of its own.
SKIP_FILES = {"LICENSE", "uv.lock", "rebrand.py"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}
TEXT_SUFFIXES = {".py", ".toml", ".md", ".yml", ".yaml", ".txt", ".cfg", ".ini", ""}

PACKAGE = re.compile(r"^[a-z][a-z0-9_]*$")
DISTRIBUTION = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
COMMAND = re.compile(r"^[a-z][a-z0-9-]*$")
ENV_PREFIX = re.compile(r"^[A-Z][A-Z0-9_]*$")
IDENTIFIER = re.compile(r"^[A-Z][A-Za-z0-9]*$")


@dataclass(frozen=True)
class Brand:
    """The names the project goes by, as brand.toml holds them."""

    display_name: str
    distribution: str
    package: str
    command: str
    env_prefix: str
    error_class: str
    repository: str

    @classmethod
    def load(cls, path: Path) -> Brand:
        """The names in ``path`` (brand.toml)."""
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls(**{field.name: str(data[field.name]) for field in fields(cls)})

    def save(self, path: Path) -> None:
        """Write these names to ``path``, with the note on how to change them."""
        lines = [
            "# The names this project goes by. Change them with 'just rebrand', never by hand: the",
            "# recipe rewrites the code, tests and docs to match, then updates this file.",
            *(f'{field.name} = "{getattr(self, field.name)}"' for field in fields(self)),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def validate(self) -> None:
        """Exit with a message when a name could not be used where it goes."""
        checks = [
            ("package", PACKAGE, "lowercase letters, digits and underscores"),
            ("distribution", DISTRIBUTION, "lowercase letters, digits and hyphens"),
            ("command", COMMAND, "lowercase letters, digits and hyphens"),
            ("env_prefix", ENV_PREFIX, "uppercase letters, digits and underscores"),
            ("error_class", IDENTIFIER, "a CamelCase Python class name"),
        ]
        for name, pattern, rule in checks:
            if not pattern.match(getattr(self, name)):
                raise SystemExit(f"--{name.replace('_', '-')} must be {rule}")
        if not self.repository.startswith("https://"):
            raise SystemExit("--repository must be an https:// URL")


def derive(current: Brand, args: argparse.Namespace) -> Brand:
    """The new brand: what was given, what follows from it, and the rest unchanged."""
    command = args.command or current.command
    package = args.package or current.package
    new = replace(
        current,
        display_name=args.display_name or current.display_name,
        command=command,
        package=package,
        distribution=args.distribution
        or (package.replace("_", "-") if args.package else current.distribution),
        env_prefix=args.env_prefix
        or (command.upper().replace("-", "_") if args.command else current.env_prefix),
        error_class=args.error_class
        or (_camel(command) + "Error" if args.command else current.error_class),
        repository=args.repository or current.repository,
    )
    new.validate()
    return new


def _camel(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[-_]", name))


def rules(old: Brand, new: Brand) -> list[tuple[re.Pattern[str], str]]:
    """Rewrites, most specific first, so a longer name is never half-replaced."""
    pairs: list[tuple[str, str]] = []

    def add(pattern: str, replacement: str) -> None:
        pairs.append((pattern, replacement))

    if old.repository != new.repository:
        add(re.escape(old.repository), new.repository)
    if old.display_name != new.display_name:
        add(re.escape(old.display_name), new.display_name)
    if old.distribution != new.distribution:
        # Not inside a URL path, where the same words may name a repository.
        add(rf"(?<![\w/-]){re.escape(old.distribution)}(?![\w-])", new.distribution)
    if old.package != new.package:
        add(rf"\b{re.escape(old.package)}\b", new.package)
    if old.error_class != new.error_class:
        add(rf"\b{re.escape(old.error_class)}\b", new.error_class)
    if old.env_prefix != new.env_prefix:
        add(rf"\b{re.escape(old.env_prefix)}_(?=[A-Z])", new.env_prefix + "_")
        add(rf'ENV_PREFIX = "{re.escape(old.env_prefix)}"', f'ENV_PREFIX = "{new.env_prefix}"')
    if old.command != new.command:
        # Case-sensitive and whole-word, so 'Ldo' in PowerShell names is left alone.
        add(rf"(?<![\w-]){re.escape(old.command)}(?![\w-])", new.command)
    return [(re.compile(pattern), replacement) for pattern, replacement in pairs]


def text_files(root: Path) -> list[Path]:
    """Every text file under ``root`` a rename may touch, skipping build output and binaries."""
    found = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.name in SKIP_FILES or path.suffix not in TEXT_SUFFIXES:
            continue
        found.append(path)
    return found


def rebrand(root: Path, old: Brand, new: Brand, *, dry_run: bool) -> list[tuple[Path, int]]:
    """Rewrite every text file under ``root``; return the files changed and how many edits."""
    compiled = rules(old, new)
    changed: list[tuple[Path, int]] = []
    for path in text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        count = 0
        for pattern, replacement in compiled:
            text, n = pattern.subn(replacement, text)
            count += n
        if count:
            changed.append((path.relative_to(root), count))
            if not dry_run:
                path.write_text(text, encoding="utf-8")
    source = root / "src" / old.package
    if old.package != new.package and source.is_dir() and not dry_run:
        target = root / "src" / new.package
        if target.exists():
            raise SystemExit(f"{target} already exists")
        source.rename(target)
    if not dry_run:
        new.save(root / "brand.toml")
    return changed


BANNER_BLOCK = re.compile(r"(# banner-start\n)BANNER = r\"\"\".*?\"\"\"\n(# banner-end)", re.S)


def set_banner(root: Path, package: str, art: str) -> None:
    """Replace the welcome banner in the brand module with ``art`` (empty for none)."""
    if not art.isascii():
        raise SystemExit("the banner must be plain ASCII, so it renders in every terminal")
    if '"""' in art:
        raise SystemExit('the banner cannot contain """')
    path = root / "src" / package / "core" / "brand.py"
    text = path.read_text(encoding="utf-8")
    body = "\n" + art.strip("\n") + "\n" if art.strip() else ""
    new, count = BANNER_BLOCK.subn(
        lambda match: f'{match.group(1)}BANNER = r"""{body}"""\n{match.group(2)}', text
    )
    if count != 1:
        raise SystemExit(f"cannot find the banner block in {path}")
    path.write_text(new, encoding="utf-8")


def verify(root: Path) -> None:
    """Refresh the lock file and environment, then run the same checks as 'just check'."""
    for command in (
        ["uv", "lock"],
        ["uv", "sync"],
        ["uv", "run", "ruff", "check", "src", "tests", "scripts"],
        ["uv", "run", "ruff", "format", "--check", "src", "tests", "scripts"],
        ["uv", "run", "mypy"],
        ["uv", "run", "pytest", "-q"],
    ):
        print("$", " ".join(command), flush=True)
        if subprocess.run(command, cwd=root, check=False).returncode != 0:
            raise SystemExit(f"'{' '.join(command)}' failed after the rename")


def main(argv: list[str] | None = None) -> None:
    """Rename the project to the names given, then prove it still passes its checks."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--display-name", help='e.g. "Contoso Helpers"')
    parser.add_argument("--command", help="the CLI command, e.g. contoso")
    parser.add_argument("--package", help="the Python import name, e.g. contoso_helpers")
    parser.add_argument(
        "--distribution", help="the package name to install; default from --package"
    )
    parser.add_argument("--env-prefix", help="environment variable prefix; default from --command")
    parser.add_argument("--error-class", help="base exception name; default from --command")
    parser.add_argument("--repository", help="the project's https URL")
    art = parser.add_mutually_exclusive_group()
    art.add_argument("--banner", type=Path, help="a file of ASCII art for the welcome banner")
    art.add_argument("--no-banner", action="store_true", help="ship without a banner")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--dry-run", action="store_true", help="show what would change")
    parser.add_argument("--no-verify", action="store_true", help="skip the lock and checks")
    args = parser.parse_args(argv)

    root: Path = args.root
    old = Brand.load(root / "brand.toml")
    new = derive(old, args)
    banner = (
        args.banner.read_text(encoding="utf-8") if args.banner else "" if args.no_banner else None
    )
    if new == old and banner is None:
        raise SystemExit("nothing to change: pass at least one new name, or a banner")
    for field in fields(Brand):
        before, after = getattr(old, field.name), getattr(new, field.name)
        if before != after:
            print(f"{field.name:>13}: {before}  ->  {after}")
    changed = rebrand(root, old, new, dry_run=args.dry_run) if new != old else []
    for path, count in changed:
        print(f"  {count:4d}  {path}")
    print(f"{'would change' if args.dry_run else 'changed'} {len(changed)} file(s)")
    if banner is not None:
        print("   banner: " + ("replaced" if banner.strip() else "removed"))
        if not args.dry_run:
            set_banner(root, new.package, banner)
    if not args.dry_run and not args.no_verify:
        verify(root)


if __name__ == "__main__":
    main()
