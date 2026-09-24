"""The tests mirror the package: one test directory per subpackage, nothing orphaned.

A new module (a vendor, a feature, a command group) gets its tests in the matching place
under tests/, and shared fakes go in tests/fakes, one module per concern.
"""

from pathlib import Path

import libre_devops_helpers as package

SRC = Path(package.__file__).parent
TESTS = Path(__file__).resolve().parents[1]
NOT_MIRRORS = {"fakes", "project", "__pycache__"}


def subpackages() -> set[Path]:
    return {init.parent.relative_to(SRC) for init in SRC.rglob("__init__.py") if init.parent != SRC}


def mirrored_directories() -> set[Path]:
    return {
        path.relative_to(TESTS)
        for path in TESTS.rglob("*")
        if path.is_dir()
        and not NOT_MIRRORS & set(path.relative_to(TESTS).parts)
        and any(path.glob("test_*.py"))
    }


def test_every_subpackage_has_a_test_directory():
    missing = sorted(str(path) for path in subpackages() - mirrored_directories())
    assert not missing, f"add tests under tests/ for: {', '.join(missing)}"


def test_every_test_directory_mirrors_a_subpackage():
    orphans = sorted(str(path) for path in mirrored_directories() - subpackages())
    assert not orphans, f"these test directories match no package: {', '.join(orphans)}"


def test_test_modules_share_code_through_fakes_only():
    offenders = []
    for path in TESTS.rglob("test_*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(("from test_", "import test_", "from tests", "import tests")):
                offenders.append(f"{path.relative_to(TESTS)}: {line}")
    assert not offenders, "import shared helpers from fakes instead:\n" + "\n".join(offenders)
