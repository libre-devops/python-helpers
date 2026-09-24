"""The README and docs/ stay true: their examples run, their links resolve."""

import re
import shlex
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from libre_devops_helpers.cli import app
from libre_devops_helpers.core import brand

ROOT = Path(__file__).resolve().parents[2]
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
BREAKS = {"|", "&&", "||", ";", ">", ">>", "<"}


def page_id(page: Path) -> str:
    return str(page.relative_to(ROOT))


def shell_lines(page: Path) -> list[list[str]]:
    """Each line of the page's bash blocks, split into words, continuations joined."""
    lines = []
    for block in re.findall(r"```bash\n(.*?)```", page.read_text(encoding="utf-8"), re.S):
        for line in re.sub(r"\\\n\s*", " ", block).splitlines():
            if line.strip():
                lines.append(shlex.split(line, comments=True))
    return lines


def invocations(page: Path, program: str) -> list[list[str]]:
    """The arguments of every ``program ...`` in the page's bash blocks, pipes and all."""
    found = []
    for words in shell_lines(page):
        segment: list[str] = []
        for word in [*words, ";"]:
            if word in BREAKS:
                if segment and segment[0] == program:
                    found.append(segment[1:])
                segment = []
            else:
                segment.append(word)
    return found


EXAMPLES = [
    pytest.param(args, id=f"{page_id(page)}: {' '.join(args)}"[:120])
    for page in PAGES
    for args in invocations(page, brand.COMMAND)
]


def test_the_docs_have_examples():
    assert len(EXAMPLES) > 100


@pytest.mark.parametrize("args", EXAMPLES)
def test_every_example_is_a_command_that_exists(args, tmp_path):
    # --help checks the command and option names without running anything.
    environ = {brand.CONFIG_ENV: str(tmp_path / "config.toml"), brand.env_var("NO_BANNER"): "1"}
    result = CliRunner().invoke(app, [*args, "--help"], env=environ)
    assert result.exit_code == 0, result.output


def recipes() -> set[str]:
    names = set()
    for line in (ROOT / "justfile").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([a-z][a-z0-9-]*)(?:\s[^:]*)?:(?!=)", line)
        if match and not line.startswith("set "):
            names.add(match.group(1))
    return names


def test_every_just_example_is_a_recipe():
    known = recipes()
    used = {args[0] for page in PAGES for args in invocations(page, "just") if args}
    assert used, "no just examples found"
    assert used <= known, used - known


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def anchors(page: Path) -> set[str]:
    text = re.sub(r"```.*?```", "", page.read_text(encoding="utf-8"), flags=re.S)
    return {slug(heading) for heading in re.findall(r"^#+\s+(.+)$", text, re.M)}


LINKS = [
    pytest.param(page, target, id=f"{page_id(page)} -> {target}")
    for page in PAGES
    for target in re.findall(r"\]\(([^)\s]+)\)", page.read_text(encoding="utf-8"))
    if not re.match(r"[a-z]+:", target)
]


@pytest.mark.parametrize(("page", "target"), LINKS)
def test_every_link_resolves(page, target):
    path, _, anchor = target.partition("#")
    destination = (page.parent / path).resolve() if path else page
    assert destination.exists(), f"{target} does not exist"
    if anchor:
        assert anchor in anchors(destination), f"{target}: no such heading"


def test_every_docs_page_a_hint_names_exists():
    source = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    pages = set(re.findall(r"""brand\.docs\(["'](\w+)["']\)""", source))
    assert pages
    for page in pages:
        assert (ROOT / "docs" / f"{page}.md").exists(), page


def test_install_lines_name_the_current_release():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    pinned = {
        found
        for page in PAGES
        for found in re.findall(r"install [^\n]*@v(\d+\.\d+\.\d+)", page.read_text())
    }
    assert pinned == {version}
