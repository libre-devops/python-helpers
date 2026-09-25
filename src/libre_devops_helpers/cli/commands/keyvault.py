"""Key Vault commands: secrets, certificates and keys close to expiry. Never reads values."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION, ERROR
from libre_devops_helpers.cli.options import (
    ColumnOption,
    FromFileOption,
    NamesArgument,
    OutputOption,
    ProfileOption,
    SheetOption,
    SortOption,
    UniqueOption,
    WhereOption,
    duration,
    get_runtime,
    names,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import MicrosoftRuntime
from libre_devops_helpers.core.errors import ApiError
from libre_devops_helpers.core.util import format_span
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.keyvault import KINDS, ItemKind, VaultItem, expiring

keyvault_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Key Vault: expiry of secrets, certificates and keys.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Add the ``keyvault`` commands to ``app``."""
    app.add_typer(keyvault_app, name="keyvault")


@keyvault_app.command("expiry")
def expiry(
    ctx: typer.Context,
    vaults: NamesArgument = None,
    from_file: FromFileOption = None,
    column: ColumnOption = None,
    sheet: SheetOption = None,
    where: WhereOption = None,
    within: Annotated[
        str, typer.Option("--within", help="Show items expiring within this, e.g. 30d.")
    ] = "30d",
    kinds: Annotated[
        list[str] | None,
        typer.Option("--kind", help="Only this kind: secret, certificate or key. Repeatable."),
    ] = None,
    include_disabled: Annotated[
        bool, typer.Option("--include-disabled", help="Include disabled items.")
    ] = False,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List secrets, certificates and keys that expire soon, or already have, in the vaults named.

    Name the vaults you look after: it has no way to search every vault, since a request
    to each one you cannot read is refused and logged, which Defender for Key Vault can
    take for reconnaissance. Exits 3 when anything is expiring, so a scheduled job can
    alert; exits 1 when no item is expiring but a vault could not be read.
    """
    window = duration(within) or timedelta(days=30)
    chosen = _kinds(kinds)
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    named = names(vaults, from_file, column, sheet, where, what="vaults")
    now = datetime.now(UTC)
    items, failed = _read_vaults(runtime, selected, named, chosen)
    shown = expiring(items, window, now=now, include_disabled=include_disabled)
    render.emit(
        output,
        ["VAULT", "KIND", "NAME", "EXPIRES", "DAYS LEFT", "ENABLED", "CONTENT TYPE"],
        [_row(item, now) for item in shown],
        [_record(item, now) for item in shown],
    )
    read = len(named) - len(failed)
    render.note(
        f"{len(shown)} item(s) expire within {format_span(window)} "
        f"({len(items)} checked in {read} of {len(named)} vault(s))"
    )
    if failed and not read:
        render.warn(f"none of the {len(named)} vault(s) could be read: see why above")
    if shown:
        raise typer.Exit(ATTENTION)
    if failed:
        raise typer.Exit(ERROR)


def _kinds(kinds: list[str] | None) -> list[ItemKind]:
    """The --kind values, checked; every kind when none is given."""
    known: dict[str, ItemKind] = {kind: kind for kind in KINDS}
    for kind in kinds or ():
        if kind not in known:
            raise typer.BadParameter(f"--kind must be one of {', '.join(KINDS)}")
    return [known[kind] for kind in kinds or KINDS]


def _read_vaults(
    runtime: MicrosoftRuntime, selected: Profile, names: list[str], kinds: list[ItemKind]
) -> tuple[list[VaultItem], list[str]]:
    """Every item of ``kinds`` in each vault, and the vaults that could not be read (each
    warned about, so one refused vault does not hide the rest)."""
    items: list[VaultItem] = []
    failed: list[str] = []
    for name in names:
        try:
            items.extend(runtime.keyvault(selected, name).items(kinds))
        except ApiError as exc:
            failed.append(name)
            render.warn(f"cannot read vault {name}: {exc}")
            if exc.hint:
                render.note(f"hint: {exc.hint}")
    return items, failed


def _record(item: VaultItem, now: datetime) -> dict[str, Any]:
    return {
        "vault": item.vault,
        "kind": item.kind,
        "name": item.name,
        "expires": item.expires,
        "days_left": item.days_left(now),
        "enabled": item.enabled,
        "attributes": item.raw.get("attributes"),
    }


def _row(item: VaultItem, now: datetime) -> list[render.Cell]:
    days = item.days_left(now)
    left: render.Cell = (
        "-"
        if days is None
        else (f"expired {-days}d ago", "red")
        if days < 0
        else (str(days), "yellow")
    )
    return [
        item.vault,
        item.kind,
        item.name,
        render.when(item.expires),
        left,
        render.yes_no(item.enabled),
        item.content_type,
    ]
