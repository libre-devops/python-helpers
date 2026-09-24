"""Azure CLI context commands: switch the active account to a profile, show the active one."""

from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import OutputOption, complete_profile, get_runtime
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core import brand
from libre_devops_helpers.microsoft.azcli import match_profile, switch_profile
from libre_devops_helpers.microsoft.process import AzCliError

az_app = typer.Typer(
    help="Azure CLI context: switch profiles, show the active account.", no_args_is_help=True
)


def register(app: typer.Typer) -> None:
    app.add_typer(az_app, name="az")


@az_app.command("use")
def use(
    ctx: typer.Context,
    name: Annotated[
        str,
        typer.Argument(help="Microsoft profile to switch to.", autocompletion=complete_profile),
    ],
    device_code: Annotated[
        bool, typer.Option("--device-code", help="Sign in with a device code, not a browser.")
    ] = False,
    no_login: Annotated[
        bool, typer.Option("--no-login", help="Fail instead of prompting when not signed in.")
    ] = False,
) -> None:
    """Switch the Azure CLI's active account to a profile, signing in when needed.

    This changes the az context for every shell. The other commands do not need
    it: they pass the profile's tenant to az explicitly.
    """
    runtime = get_runtime(ctx).microsoft
    result = switch_profile(
        runtime.az, runtime.config().get(name), sign_in=not no_login, device_code=device_code
    )
    account = result.account
    target = "tenant-level account" if account.tenant_level else f"{account.name} ({account.id})"
    render.echo(
        f"Switched to {name}: {target} in tenant {account.tenant_id} "
        f"as {account.user or 'unknown user'}"
    )


@az_app.command("whoami")
def whoami(ctx: typer.Context, output: OutputOption = Output.TABLE) -> None:
    """Show the Azure CLI's active account and the profile it matches."""
    runtime = get_runtime(ctx).microsoft
    account = runtime.az.current_account()
    if account is None:
        raise AzCliError(
            "the Azure CLI is not signed in", hint=f"run {brand.command('az use <profile>')}"
        )
    config = runtime.optional_config()
    profile = match_profile(config.profiles.values(), account) if config else None
    data = {
        "profile": profile.name if profile else None,
        "tenant_id": account.tenant_id,
        "subscription_id": None if account.tenant_level else account.id,
        "subscription_name": None if account.tenant_level else account.name,
        "user": account.user,
        "state": account.state,
    }
    if output is not Output.TABLE:
        render.emit(output, list(data), [[str(value or "") for value in data.values()]], data)
        return
    render.echo(
        render.pairs(
            [
                ("Profile", data["profile"] or "(no matching profile)"),
                ("Tenant", account.tenant_id),
                (
                    "Subscription",
                    "tenant-level account"
                    if account.tenant_level
                    else f"{account.name} ({account.id})",
                ),
                ("User", account.user),
                ("State", account.state),
            ]
        )
    )
