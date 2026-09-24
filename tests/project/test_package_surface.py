"""The package's public surface, and the layering between its parts.

- core is vendor-neutral and imports nothing else in the package.
- A vendor layer's shared modules (microsoft/*.py, microsoft/auth) import core and each
  other only.
- Each feature module (microsoft/entra, ...) imports core and its vendor's shared layer.
- A composite module (microsoft/devices) may also import the features it combines.
- Only cli may exit or print, so nothing imports cli, and cli may import anything."""

import ast
import importlib
from pathlib import Path

import pytest

import libre_devops_helpers as package

ROOT = Path(package.__file__).parent

NAME = package.__name__

VENDORS = {
    "microsoft": [
        "azcli",
        "automation",
        "entra",
        "graph",
        "xdr",
        "incidents",
        "intune",
        "azure",
        "keyvault",
        "loganalytics",
        "logicapps",
        "pim",
    ],
    "servicenow": ["instance"],
}

SHARED = {"microsoft": ["auth"], "servicenow": []}

COMPOSITES = {"microsoft.devices": {"microsoft.entra", "microsoft.xdr", "microsoft.intune"}}


def allowed() -> dict[str, set[str]]:
    rules: dict[str, set[str]] = {"core": {"core"}}
    everything = {"core", "cli"}
    for vendor, features in VENDORS.items():
        rules[vendor] = {"core", vendor}
        everything.add(vendor)
        for feature in features:
            layer = f"{vendor}.{feature}"
            rules[layer] = {"core", vendor, layer}
            everything.add(layer)
    for composite, uses in COMPOSITES.items():
        vendor = composite.split(".")[0]
        rules[composite] = {"core", vendor, composite, *uses}
        everything.add(composite)
    rules["cli"] = everything
    return rules


ALLOWED = allowed()


def layer_of(module: str) -> str | None:
    """The layer a dotted module name belongs to, or None for the package root."""
    parts = module.split(".")
    if parts[0] != NAME or len(parts) == 1:
        return None
    top = parts[1]
    if top in VENDORS and len(parts) > 2 and f"{top}.{parts[2]}" in ALLOWED:
        return f"{top}.{parts[2]}"
    return top


def layer_of_file(path: Path) -> str | None:
    """The layer a source file belongs to; None for the package root's own files."""
    if path.parent == ROOT:
        return None
    relative = path.relative_to(ROOT).with_suffix("")
    return layer_of(".".join([NAME, *relative.parts]))


def imported_layers(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            # 'from package.microsoft import entra' names a module in the import list.
            modules = [f"{node.module}.{alias.name}" for alias in node.names]
        for module in modules:
            layer = layer_of(module)
            if layer is not None and not module.endswith(".__version__"):
                found.add(layer)
    return found


def test_every_package_is_covered_by_the_layering_rules():
    tops = {path.name for path in ROOT.iterdir() if (path / "__init__.py").exists()}
    assert tops == {"core", "cli", *VENDORS}
    for vendor, features in VENDORS.items():
        subpackages = {p.name for p in (ROOT / vendor).iterdir() if (p / "__init__.py").exists()}
        composites = {name.split(".")[1] for name in COMPOSITES if name.startswith(vendor + ".")}
        assert subpackages == {*features, *SHARED[vendor], *composites}


@pytest.mark.parametrize("path", sorted(ROOT.rglob("*.py")), ids=lambda p: str(p.relative_to(ROOT)))
def test_each_module_imports_only_what_its_layer_may(path):
    layer = layer_of_file(path)
    if layer is None:
        return
    assert layer in ALLOWED, f"{path.relative_to(ROOT)} is in no known layer"
    extra = imported_layers(path) - ALLOWED[layer]
    assert not extra, f"{path.relative_to(ROOT)} ({layer}) imports {sorted(extra)}"


PACKAGES = [
    f"{NAME}.core",
    f"{NAME}.cli",
    *(f"{NAME}.{vendor}" for vendor in VENDORS),
    *(f"{NAME}.{vendor}.{name}" for vendor, names in VENDORS.items() for name in names),
    *(f"{NAME}.{vendor}.{name}" for vendor, names in SHARED.items() for name in names),
    *(f"{NAME}.{name}" for name in COMPOSITES),
]


@pytest.mark.parametrize("name", PACKAGES)
def test_exports_resolve(name):
    module = importlib.import_module(name)
    assert module.__all__
    for export in module.__all__:
        assert getattr(module, export) is not None, f"{name}.{export}"


@pytest.mark.parametrize(
    "feature", [f"{v}.{f}" for v, features in VENDORS.items() for f in features if f != "azcli"]
)
def test_every_feature_module_declares_its_permission_requirements(feature):
    module = importlib.import_module(f"{NAME}.{feature}")
    assert isinstance(module.REQUIREMENTS, tuple)


def test_the_version_is_the_same_everywhere():
    # The release workflow checks the tag against pyproject.toml; the CLI reports
    # __version__. Both must agree, or 'ldo --version' would name the wrong release.
    import tomllib

    pyproject = tomllib.loads((ROOT.parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == package.__version__
