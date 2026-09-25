"""The profiles command: every profile the config file defines, for every vendor."""

from dataclasses import dataclass
from typing import Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    OutputOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.microsoft.azcli import find_account, match_profile
from libre_devops_helpers.microsoft.config import Profile
from libre_devops_helpers.microsoft.process import AzCliError
from libre_devops_helpers.servicenow import OAuthCredential
from libre_devops_helpers.servicenow import Profile as ServiceNowProfile


def register(app: typer.Typer) -> None:
    """Add the ``profiles`` command to ``app``."""
    app.command("profiles")(profiles)


def profiles(
    ctx: typer.Context,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List configured profiles, which is active, and whether each can sign in."""
    runtime = get_runtime(ctx)
    runtime.config_file()
    rows, records = _microsoft(runtime)
    snow_rows, snow_records = _servicenow(runtime)
    rows += snow_rows
    records += snow_records
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
        state = _State(
            default=profile.name == config.default_profile,
            active=active is not None and profile.name == active.name,
            signed_in=None if accounts is None else find_account(accounts, profile) is not None,
        )
        rows.append(_microsoft_row(profile, state))
        records.append(_microsoft_record(profile, state))
    placeholders = [p.name for p in config.profiles.values() if p.has_placeholder_ids]
    if placeholders:
        render.warn(f"placeholder ids in {', '.join(placeholders)}; edit {config.path}")
    return rows, records


@dataclass(frozen=True)
class _State:
    """How a Microsoft profile stands: the config's default, the Azure CLI's active
    account, and signed in to the Azure CLI (None when that could not be read)."""

    default: bool
    active: bool
    signed_in: bool | None


def _microsoft_row(profile: Profile, state: _State) -> list[render.Cell]:
    target = (
        f"subscription {profile.subscription_id}"
        if profile.subscription_id
        else f"tenant {profile.tenant_id}"
    )
    if profile.cloud.name != "public":
        target += f" ({profile.cloud.name})"
    return [
        "microsoft",
        ("*", "green") if state.active else " ",
        profile.name + (" (default)" if state.default else ""),
        target,
        profile.auth,
        _signed_in_cell(profile.auth, state.signed_in),
        profile.description,
    ]


def _microsoft_record(profile: Profile, state: _State) -> dict[str, Any]:
    return {
        "vendor": "microsoft",
        "name": profile.name,
        "kind": profile.kind,
        "tenant_id": profile.tenant_id,
        "subscription_id": profile.subscription_id,
        "cloud": profile.cloud.name,
        "auth": profile.auth,
        "description": profile.description,
        "default": state.default,
        "active": state.active,
        "signed_in": state.signed_in,
    }


def _servicenow(runtime: Runtime) -> tuple[list[list[render.Cell]], list[dict[str, Any]]]:
    snow = runtime.servicenow
    config = snow.config()
    default = config.default_profile if config else None
    rows: list[list[render.Cell]] = []
    records: list[dict[str, Any]] = []
    for profile in snow.profiles():
        signed_in = _snow_signed_in(runtime, profile)
        method = f"oauth ({profile.sign_in})" if profile.auth == "oauth" else profile.auth
        records.append(
            {
                "vendor": "servicenow",
                "name": profile.name,
                "instance": profile.instance,
                "auth": profile.auth,
                "sign_in": profile.sign_in if profile.auth == "oauth" else None,
                "description": profile.description,
                "default": profile.name == default,
                "signed_in": signed_in,
            }
        )
        rows.append(
            [
                "servicenow",
                " ",
                profile.name + (" (default)" if profile.name == default else ""),
                profile.host,
                method,
                "?" if signed_in is None else ("yes", "green") if signed_in else ("no", "yellow"),
                profile.description,
            ]
        )
    return rows, records


def _snow_signed_in(runtime: Runtime, profile: ServiceNowProfile) -> bool | None:
    """Whether a command could sign in now, without asking: a kept sign-in, or a password."""
    if profile.auth == "basic":
        return bool(runtime.environ.get(profile.password_env))
    if profile.token_cache == "keychain":
        return None  # reading the keychain can prompt; not worth it for a listing
    try:
        credential = runtime.servicenow.credential(profile)
    except LdoError:
        return False
    return isinstance(credential, OAuthCredential) and credential.has_kept_sign_in()


def _signed_in_cell(auth: str, signed_in: bool | None) -> render.Cell:
    # Only azure-cli profiles depend on an az session; the others bring their own.
    if auth != "azure-cli":
        return ("n/a", None)
    if signed_in is None:
        return "?"
    return ("yes", "green") if signed_in else ("no", "yellow")
