"""Errors say what kind they are: a caller can tell a bad input from a failed call.

Library and CLI code raise a subclass of LdoError (InputError, ConfigError, AuthError,
NotFoundError, ApiError, ...), never the base class itself, which says only that
something in this package went wrong.
"""

import ast
from pathlib import Path

import libre_devops_helpers as package

ROOT = Path(package.__file__).parent


def test_no_code_raises_the_base_error_class():
    offenders = []
    for path in sorted(ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(raised, ast.Name) and raised.id == "LdoError":
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == [], "raise a specific kind of LdoError: " + ", ".join(offenders)
