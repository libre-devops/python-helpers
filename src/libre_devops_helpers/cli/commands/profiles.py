"""The profiles command: every profile the config file defines, for every vendor."""

from typing import Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import OutputOption, get_runtime
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core import brand
from libre_devops_helpers.microsoft.azcli import find_account, match_profile
from libre_devops_helpers.microsoft.process import AzCliError


def register(app: typer.Typer) -> None:
    app.command("profiles")(profiles)


def profiles(ctx: typer.Context, output: OutputOption = Output.TABLE) -> None:
    """List configured profiles, which is active, and whether each can sign in."""
    runtime = get_runtime(ctx)
    runtime.config_file()
    rows, records = _microsoft(runtime)
    render.emit(
        output,
        ["VENDOR", "", "PROFILE", "TARGET", "AUTH", "SIGNED IN", "DESCRIPTION"],
        rows,
        records,
    )
    if not rows:
        render.warn(f"no profiles configured; {brand.command('config init')} writes a template")


def _microsoft(runtime: Runtime) -> tuple[list[list[render.Cell]], list[dict[str, Any]]]:
    ms = runtime.microsoft
    config = ms.optional_config()
    if config is None:
        return [], []
    try:
        accounts = ms.az.accounts()
    except AzCliError as exc:
        render.warn(f"cannot read Azure CLI accounts: {exc}")
        accounts = None
    active_account = next((account for account in accounts or [] if account.is_default), None)
    active = match_profile(config.profiles.values(), active_account) if active_account else None

    rows: list[list[render.Cell]] = []
    records: list[dict[str, Any]] = []
    for profile in config.profiles.values():
        signed_in = None if accounts is None else find_account(accounts, profile) is not None
        is_active = active is not None and profile.name == active.name
        is_default = profile.name == config.default_profile
        records.append(
            {
                "vendor": "microsoft",
                "name": profile.name,
                "kind": profile.kind,
                "tenant_id": profile.tenant_id,
                "subscription_id": profile.subscription_id,
                "cloud": profile.cloud.name,
                "auth": profile.auth,
                "description": profile.description,
                "default": is_default,
                "active": is_active,
                "signed_in": signed_in,
            }
        )
        target = (
            f"subscription {profile.subscription_id}"
            if profile.subscription_id
            else f"tenant {profile.tenant_id}"
        )
        if profile.cloud.name != "public":
            target += f" ({profile.cloud.name})"
        rows.append(
            [
                "microsoft",
                ("*", "green") if is_active else " ",
                profile.name + (" (default)" if is_default else ""),
                target,
                profile.auth,
                _signed_in_cell(profile.auth, signed_in),
                profile.description,
            ]
        )
    placeholders = [p.name for p in config.profiles.values() if p.has_placeholder_ids]
    if placeholders:
        render.warn(f"placeholder ids in {', '.join(placeholders)}; edit {config.path}")
    return rows, records


def _signed_in_cell(auth: str, signed_in: bool | None) -> render.Cell:
    # Only azure-cli profiles depend on an az session; the others bring their own.
    if auth != "azure-cli":
        return ("n/a", None)
    if signed_in is None:
        return "?"
    return ("yes", "green") if signed_in else ("no", "yellow")
