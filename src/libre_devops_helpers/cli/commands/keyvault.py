"""Key Vault commands: secrets, certificates and keys close to expiry. Never reads values."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION, ERROR
from libre_devops_helpers.cli.options import (
    NamesArgument,
    OutputOption,
    ProfileOption,
    duration,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core.errors import ApiError, InputError
from libre_devops_helpers.core.inputs import read_names
from libre_devops_helpers.core.util import format_duration
from libre_devops_helpers.microsoft.keyvault import KINDS, ItemKind, VaultItem, expiring

keyvault_app = typer.Typer(
    rich_markup_mode="markdown",
    help="Key Vault: expiry of secrets, certificates and keys.",
    no_args_is_help=True,
)

# Every vault the credential can see, across subscriptions, in one query.
_VAULTS_QUERY = (
    "resources | where type =~ 'microsoft.keyvault/vaults' "
    "| project name, subscriptionId, resourceGroup | order by name asc"
)


def register(app: typer.Typer) -> None:
    app.add_typer(keyvault_app, name="keyvault")


@keyvault_app.command("expiry")
def expiry(
    ctx: typer.Context,
    vaults: NamesArgument = None,
    all_vaults: Annotated[
        bool,
        typer.Option(
            "--all-vaults", help="Find every vault through Resource Graph and check each."
        ),
    ] = False,
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
    output: OutputOption = Output.TABLE,
) -> None:
    """List secrets, certificates and keys that expire soon, or already have.

    Exits 3 when anything is expiring, so a scheduled job can alert; exits 1 when no
    item is expiring but a vault could not be read.
    """
    window = duration(within) or timedelta(days=30)
    known: dict[str, ItemKind] = {kind: kind for kind in KINDS}
    chosen: list[ItemKind] = []
    for kind in kinds or KINDS:
        if kind not in known:
            raise typer.BadParameter(f"--kind must be one of {', '.join(KINDS)}")
        chosen.append(known[kind])
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    names = read_names(vaults or [])
    if all_vaults:
        scope = [selected.subscription_id] if selected.subscription_id else []
        found = runtime.azure(selected).resource_graph(_VAULTS_QUERY, subscriptions=scope)
        names.extend(str(row.get("name")) for row in found.rows if row.get("name"))
    if not names:
        raise InputError("no vaults given", hint="name them, or pass --all-vaults")

    now = datetime.now(UTC)
    items: list[VaultItem] = []
    failed: list[str] = []
    for name in dict.fromkeys(names):
        try:
            items.extend(runtime.keyvault(selected, name).items(chosen))
        except ApiError as exc:
            failed.append(name)
            render.warn(f"cannot read vault {name}: {exc}")
            if exc.hint:
                render.note(f"hint: {exc.hint}")
    shown = expiring(items, window, now=now, include_disabled=include_disabled)
    render.emit(
        output,
        ["VAULT", "KIND", "NAME", "EXPIRES", "DAYS LEFT", "ENABLED", "CONTENT TYPE"],
        [_row(item, now) for item in shown],
        [
            {
                "vault": item.vault,
                "kind": item.kind,
                "name": item.name,
                "expires": item.expires,
                "days_left": item.days_left(now),
                "enabled": item.enabled,
                "attributes": item.raw.get("attributes"),
            }
            for item in shown
        ],
    )
    checked = len(dict.fromkeys(names)) - len(failed)
    render.note(
        f"{len(shown)} item(s) expire within {format_duration(window)} "
        f"({len(items)} checked in {checked} vault(s))"
    )
    if shown:
        raise typer.Exit(ATTENTION)
    if failed:
        raise typer.Exit(ERROR)


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
