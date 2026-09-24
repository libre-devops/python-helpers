"""'just rebrand' must keep working as the code grows, so rebrand a copy and run it.

The copy is renamed with made-up names, checked for any trace of the old ones, and then
its whole test suite and its CLI run from the renamed package."""

import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

SKIP = shutil.ignore_patterns(
    ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build", "uv.lock"
)

BANNER = r"""
   ___  _   _ ___  ___  _  _
  / _ \| | | |_ _|/ __|| \| |   an example logo
 | (_) | |_| || || (__ | .` |
  \__\_\\___/|___|\___||_|\_|
"""


@pytest.fixture(scope="module")
def rebranded(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("rebrand") / "repo"
    shutil.copytree(REPO, root, ignore=SKIP)
    banner = root.parent / "banner.txt"
    banner.write_text(BANNER, encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "rebrand.py"),
            "--root",
            str(root),
            "--command",
            "quincy",
            "--package",
            "quincy_tools",
            "--display-name",
            "Quincy Tools",
            "--repository",
            "https://git.example.test/platform/quincy",
            "--banner",
            str(banner),
            "--no-verify",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return root


def old_names() -> list[re.Pattern[str]]:
    brand = tomllib.loads((REPO / "brand.toml").read_text(encoding="utf-8"))
    return [
        re.compile(re.escape(brand["display_name"])),
        re.compile(rf"(?<![\w/-]){re.escape(brand['distribution'])}(?![\w-])"),
        re.compile(rf"\b{re.escape(brand['package'])}\b"),
        re.compile(rf"\b{re.escape(brand['error_class'])}\b"),
        re.compile(rf"\b{re.escape(brand['env_prefix'])}_(?=[A-Z])"),
        re.compile(rf"(?<![\w-]){re.escape(brand['command'])}(?![\w-])"),
        re.compile(re.escape(brand["repository"])),
    ]


def test_no_old_name_survives_outside_the_licence(rebranded):
    patterns = old_names()
    leftovers = []
    for path in rebranded.rglob("*"):
        if not path.is_file() or path.name in {"LICENSE", "rebrand.py", "test_rebrand.py"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                leftovers.append(f"{path.relative_to(rebranded)}:{line}: {match.group(0)}")
    assert not leftovers, "\n".join(leftovers[:20])


def test_the_licence_and_its_notice_are_untouched(rebranded):
    assert (rebranded / "LICENSE").read_bytes() == (REPO / "LICENSE").read_bytes()


def test_the_package_moved_and_brand_toml_records_the_new_names(rebranded):
    assert (rebranded / "src" / "quincy_tools").is_dir()
    assert not any((rebranded / "src").glob("libre*"))
    brand = tomllib.loads((rebranded / "brand.toml").read_text(encoding="utf-8"))
    assert brand == {
        "display_name": "Quincy Tools",
        "distribution": "quincy-tools",
        "package": "quincy_tools",
        "command": "quincy",
        "env_prefix": "QUINCY",
        "error_class": "QuincyError",
        "repository": "https://git.example.test/platform/quincy",
    }
    pyproject = tomllib.loads((rebranded / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "quincy-tools"
    assert pyproject["project"]["scripts"] == {"quincy": "quincy_tools.cli:main"}


def environment(root: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("LDO_")}
    return {**env, "PYTHONPATH": str(root / "src"), "NO_COLOR": "1"}


def test_the_rebranded_cli_runs_under_its_new_names(rebranded, tmp_path):
    env = {**environment(rebranded), "QUINCY_CONFIG": str(tmp_path / "config.toml")}
    run = [sys.executable, "-m", "quincy_tools"]
    version = subprocess.run([*run, "--version"], env=env, capture_output=True, text=True)
    assert version.stdout.startswith("quincy ")
    welcome = subprocess.run([*run, "welcome"], env=env, capture_output=True, text=True)
    assert "an example logo" in welcome.stderr
    assert "Quincy Tools  quincy" in welcome.stderr
    assert "'quincy config init'" not in welcome.stdout  # suggestions are shown unquoted
    assert "quincy config init" in welcome.stdout
    missing = subprocess.run([*run, "profiles"], env=env, capture_output=True, text=True)
    assert missing.returncode == 1
    assert "create one with 'quincy config init'" in missing.stderr


def test_the_rebranded_test_suite_passes(rebranded):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--ignore=tests/project/test_rebrand.py",
        ],
        cwd=rebranded,
        env=environment(rebranded),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
