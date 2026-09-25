"""The json command: pretty-print JSON from anywhere, in colour on a terminal, or as YAML.

For JSON that did not come from this tool: 'az rest', curl, a file. It reads one JSON
document, or JSON Lines (one document per line, as OTLP logs and many APIs write them).
"""

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from libre_devops_helpers.core import brand, yaml_text
from libre_devops_helpers.core import colour as core_colour
from libre_devops_helpers.core.errors import InputError


def register(app: typer.Typer) -> None:
    """Add the ``json`` command to ``app``."""
    app.command("json")(pretty)


def pretty(
    file: Annotated[
        Path | None,
        typer.Argument(
            metavar="[FILE]",
            help="A JSON or JSON Lines file. Omit, or pass -, to read stdin.",
            show_default=False,
        ),
    ] = None,
    sort_keys: Annotated[bool, typer.Option("--sort-keys", help="Sort object keys.")] = False,
    compact: Annotated[
        bool, typer.Option("--compact", "-c", help="One line per document, no spaces.")
    ] = False,
    indent: Annotated[int, typer.Option("--indent", min=0, max=8, help="Spaces per level.")] = 2,
    yaml: Annotated[bool, typer.Option("--yaml", help="Write it as YAML instead.")] = False,
    colour: Annotated[
        bool | None,
        typer.Option(
            "--colour/--no-colour",
            help="Colour it, e.g. for less -R. Default: on a terminal, unless NO_COLOR is set.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Pretty-print JSON from stdin or a file, in colour on a terminal, or as YAML.

    For JSON from anywhere, e.g. az rest --url ... | ldo json. It reads one document, or
    JSON Lines, and shows it indented, with keys, strings, numbers and brackets coloured
    (brackets by how deeply they nest). Piped on, it stays plain. --yaml writes YAML.
    """
    documents = _documents(_read(file))
    painted = core_colour.wanted() if colour is None else colour
    if yaml:
        if compact:
            raise InputError("--compact is for JSON; YAML has no one-line form here")
        # YAML's colours are JSON's: keys, strings, numbers, booleans, null.
        paint = core_colour.paint if painted else None
        for number, document in enumerate(documents):
            if number:
                typer.echo(core_colour.style("---", dim=True) if painted else "---", color=painted)
            data = _sorted(document) if sort_keys else document
            typer.echo(
                yaml_text.dumps(data, indent=indent or 2, paint=paint), nl=False, color=painted
            )
        return
    spacing = None if compact else indent
    for document in documents:
        if painted:
            text = core_colour.json_text(document, indent=spacing, sort_keys=sort_keys)
        else:
            text = json.dumps(
                document,
                indent=spacing,
                sort_keys=sort_keys,
                ensure_ascii=False,
                separators=(",", ":") if compact else None,
            )
        typer.echo(text, color=painted)


def _sorted(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted(item) for item in value]
    return value


def _read(file: Path | None) -> str:
    if file is not None and str(file) != "-":
        try:
            return file.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            raise InputError(f"no such file: {file}") from None
        except (OSError, UnicodeDecodeError) as exc:
            raise InputError(f"cannot read {file}: {exc}") from None
    if sys.stdin.isatty():
        raise InputError(
            "no JSON to show", hint=f"pipe some in, e.g. az rest --url ... | {brand.COMMAND} json"
        )
    return sys.stdin.read()


def _documents(text: str) -> list[Any]:
    """One JSON document, or each line of JSON Lines. A bad one says where it broke."""
    if not text.strip():
        raise InputError("the input is empty")
    try:
        return [json.loads(text)]
    except json.JSONDecodeError as whole:
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            raise _not_json(whole) from None
        documents = []
        for line in lines:
            try:
                documents.append(json.loads(line))
            except json.JSONDecodeError:
                # Neither one document nor JSON Lines: report the document's own error.
                raise _not_json(whole) from None
        return documents


def _not_json(error: json.JSONDecodeError) -> InputError:
    return InputError(f"not JSON: {error.msg} at line {error.lineno}, column {error.colno}")
