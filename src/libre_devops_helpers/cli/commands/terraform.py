"""``terraform``: a module's variables and outputs in name order, and its README from its
HEADER.md and terraform-docs."""

from pathlib import Path
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import OutputOption, SortOption, UniqueOption, get_runtime
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.terraform.docs import HEADER, README, Readme, document, folders
from libre_devops_helpers.terraform.sort import KINDS, Sorting, sort_file, targets
from libre_devops_helpers.terraform.tools import format_code, formatter, terraform_docs

terraform_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Terraform modules: their variables and outputs in name order, and their README "
    "from HEADER.md and terraform-docs. Changes only the files of the folders named.",
    no_args_is_help=True,
)

RecursiveOption = Annotated[
    bool,
    typer.Option(
        "--recursive", "-r", help="Every folder beneath too: examples/, modules/ and the like."
    ),
]
CheckOption = Annotated[
    bool,
    typer.Option("--check", help="Change nothing: say which would change, and exit 3 if any."),
]
# How each kind of block reads in a table.
_KIND_NAMES = {"variable": "variables", "output": "outputs"}


def register(app: typer.Typer) -> None:
    """Add the ``terraform`` commands to ``app``."""
    app.add_typer(terraform_app, name="terraform")


@terraform_app.command("sort")
def sort_blocks(
    ctx: typer.Context,
    paths: Annotated[
        list[Path] | None,
        typer.Argument(
            metavar="[PATH]...",
            help="Module folders (their variables.tf and outputs.tf) or .tf files; "
            "the current folder by default.",
        ),
    ] = None,
    inputs: Annotated[
        bool, typer.Option("--inputs", help="Only the variables: a folder's variables.tf.")
    ] = False,
    outputs: Annotated[
        bool, typer.Option("--outputs", help="Only the outputs: a folder's outputs.tf.")
    ] = False,
    recursive: RecursiveOption = False,
    check: CheckOption = False,
    no_fmt: Annotated[
        bool, typer.Option("--no-fmt", help="Do not run terraform fmt after sorting.")
    ] = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Put a module's variables and outputs in name order, as terraform-docs lists them,
    then run terraform fmt on it.

    Only the blocks move: the comments just above one move with it, and all else in the
    file stays where it was. Without --inputs or --outputs, both. terraform fmt is
    terraform's, or OpenTofu's tofu when terraform is not on PATH; with neither, the files
    are still sorted, and a warning says so. --check changes nothing and exits 3 when a
    file is not in order, for a pipeline.
    """
    chosen = paths or [Path(".")]
    kinds = _kinds(inputs=inputs, outputs=outputs)
    found: list[Sorting] = []
    for path, file_kinds in targets(chosen, kinds, recursive=recursive):
        found += sort_file(path, file_kinds, write=not check)
    render.emit(
        output,
        ["FILE", "BLOCKS", "COUNT", "STATE"],
        [
            [str(item.path), _KIND_NAMES[item.kind], str(item.count), _sort_cell(item, check)]
            for item in found
        ],
        [_sort_record(item, check) for item in found],
    )
    moved = sum(1 for item in found if not item.in_order)
    if check:
        render.note(
            f"{moved} of {len(found)} not in order" + (": run without --check" * bool(moved))
        )
        if moved:
            raise typer.Exit(ATTENTION)
        return
    render.note(f"sorted {moved} of {len(found)}; the rest were in order")
    if not no_fmt:
        _format(get_runtime(ctx), chosen, recursive=recursive)


@terraform_app.command("docs")
def docs(
    ctx: typer.Context,
    paths: Annotated[
        list[Path] | None,
        typer.Argument(metavar="[FOLDER]...", help="Module folders; the current one by default."),
    ] = None,
    header: Annotated[
        str, typer.Option("--header", help="The file in each folder with the README's top.")
    ] = HEADER,
    readme: Annotated[
        str, typer.Option("--readme", help="The README to write, in each folder.")
    ] = README,
    recursive: RecursiveOption = False,
    check: CheckOption = False,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Write each module's README: its HEADER.md at the top, then the section terraform-docs
    writes between its markers.

    terraform-docs is not part of this, and must be on PATH: it reads the module's own
    .terraform-docs.yml when it has one, and writes a Markdown table when not. A folder
    without a HEADER.md keeps its README's own top. With --recursive, every folder beneath
    with a HEADER.md of its own (an example, a submodule) too. --check changes nothing and
    exits 3 when a README is out of date.
    """
    for name, option in ((header, "--header"), (readme, "--readme")):
        if Path(name).name != name or name in {"", ".", ".."}:
            raise typer.BadParameter("give a file name, found in each folder", param_hint=option)
    runtime = get_runtime(ctx)
    tool = terraform_docs(which=runtime.find_command, runner=runtime.command_runner)
    found = [
        document(folder, tool=tool, check=check, header_name=header, readme_name=readme)
        for folder in folders(paths or [Path(".")], recursive=recursive, header_name=header)
    ]
    render.emit(
        output,
        ["README", "HEADER", "STATE"],
        [
            [str(item.path), item.header.name if item.header else "-", _readme_cell(item)]
            for item in found
        ],
        [
            {
                "folder": str(item.folder),
                "readme": str(item.path),
                "header": str(item.header) if item.header else None,
                "state": item.state,
            }
            for item in found
        ],
    )
    stale = sum(1 for item in found if item.state == "out of date")
    if check and stale:
        render.note(f"{stale} of {len(found)} out of date: run without --check")
        raise typer.Exit(ATTENTION)


def _kinds(*, inputs: bool, outputs: bool) -> tuple[str, ...]:
    """The kinds of block asked for: both when neither flag, or both, are given."""
    if inputs == outputs:
        return KINDS
    return ("variable",) if inputs else ("output",)


def _format(runtime: Runtime, chosen: list[Path], *, recursive: bool) -> None:
    tool = formatter(which=runtime.find_command, runner=runtime.command_runner)
    if tool is None:
        render.warn("terraform fmt not run: neither terraform nor tofu is on PATH (--no-fmt)")
        return
    changed = format_code(tool, chosen, recursive=recursive)
    render.note(f"{tool.name} fmt formatted {len(changed)} file(s)")


def _sort_state(item: Sorting, check: bool) -> str:
    if item.in_order:
        return "in order"
    return "out of order" if check else "sorted"


def _sort_cell(item: Sorting, check: bool) -> render.Cell:
    state = _sort_state(item, check)
    return (state, "yellow" if state == "out of order" else "green")


def _sort_record(item: Sorting, check: bool) -> dict[str, Any]:
    return {
        "file": str(item.path),
        "blocks": _KIND_NAMES[item.kind],
        "count": item.count,
        "in_order": item.in_order,
        "state": _sort_state(item, check),
    }


def _readme_cell(item: Readme) -> render.Cell:
    return (item.state, "yellow" if item.state == "out of date" else "green")
