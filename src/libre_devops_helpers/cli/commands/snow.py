"""ServiceNow commands: sign in, who you are, the instance, and its applications."""

from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import OutputOption, get_runtime
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.servicenow import OAuthCredential
from libre_devops_helpers.servicenow import instance as instance_feature

snow_app = typer.Typer(
    rich_markup_mode="markdown",
    name="snow",
    help="ServiceNow: sign in, who you are, the instance and its applications.",
    no_args_is_help=True,
)

# Every ServiceNow feature declares the roles its calls need; whoami reports each one.
REQUIREMENTS = (*instance_feature.REQUIREMENTS,)


def register(app: typer.Typer) -> None:
    app.add_typer(snow_app)


def _complete_profile(incomplete: str) -> list[str]:
    try:
        names = [profile.name for profile in Runtime().servicenow.profiles()]
    except LdoError:
        return []
    return [name for name in sorted(names) if name.startswith(incomplete)]


ProfileOption = Annotated[
    str | None,
    typer.Option(
        "--profile",
        "-p",
        envvar=brand.env_var("SNOW_PROFILE"),
        help="ServiceNow profile. Default: default_profile, else the one from the environment.",
        autocompletion=_complete_profile,
        show_default=False,
    ),
]


@snow_app.command("sign-in")
def sign_in(ctx: typer.Context, profile: ProfileOption = None) -> None:
    """Sign in afresh and keep the sign-in, so later commands do not ask.

    With sign_in = "browser" (the default) you get a link to open in any browser, where
    you sign in as you do to the instance (single sign-on and MFA too); then paste back
    the address it lands on. With sign_in = "password" you are asked for the password,
    unless it is in the environment.
    """
    runtime = get_runtime(ctx).servicenow
    selected = runtime.profile(profile)
    credential = runtime.credential(selected)
    if not isinstance(credential, OAuthCredential):
        raise LdoError(
            f"profile {selected.name!r} uses basic sign-in, which sends the password each time",
            hint=runtime.oauth_hint(selected),
        )
    credential.sign_in()
    user = runtime.instance(selected).current_user()
    render.note(
        f"Signed in to {selected.host} as {user.user_name} ({user.name}). "
        f"The sign-in is kept ({selected.token_cache}); "
        f"{brand.command(f'snow sign-out -p {selected.name}')} forgets it."
    )


@snow_app.command("sign-out")
def sign_out(ctx: typer.Context, profile: ProfileOption = None) -> None:
    """Forget the kept sign-in, so the next command signs in afresh."""
    runtime = get_runtime(ctx).servicenow
    selected = runtime.profile(profile)
    credential = runtime.credential(selected)
    if not isinstance(credential, OAuthCredential):
        render.note(f"profile {selected.name!r} uses basic sign-in, so nothing is kept")
        return
    if credential.sign_out():
        render.note(f"Forgot the sign-in kept for {selected.name} ({selected.host}).")
    else:
        render.note(f"No sign-in was kept for {selected.name}.")


@snow_app.command("whoami")
def whoami(
    ctx: typer.Context, profile: ProfileOption = None, output: OutputOption = Output.TABLE
) -> None:
    """Show who you are signed in as, your roles, and which features they cover."""
    runtime = get_runtime(ctx).servicenow
    selected = runtime.profile(profile)
    client = runtime.instance(selected)
    user = client.current_user()
    roles = client.roles(user)
    covers = [(item.feature, item.met_by(roles)) for item in REQUIREMENTS]
    record = {
        "profile": selected.name,
        "instance": selected.instance,
        "auth": selected.auth,
        "sign_in": selected.sign_in if selected.auth == "oauth" else None,
        "user": dict(user.raw),
        "roles": list(roles),
        "covers": {feature: met for feature, met in covers},
    }
    if output is not Output.TABLE:
        render.emit(
            output,
            ["PROFILE", "INSTANCE", "USER", "NAME", "ROLES"],
            [[selected.name, selected.host, user.user_name, user.name, " ".join(roles)]],
            record,
        )
        return
    method = f"oauth ({selected.sign_in})" if selected.auth == "oauth" else selected.auth
    render.echo(
        render.pairs(
            [
                ("Profile", selected.name),
                ("Instance", selected.instance),
                ("Sign-in", method),
                ("User", f"{user.user_name} ({user.name})"),
                ("Email", user.email),
                ("Roles", ", ".join(roles) or "(none)"),
            ]
        )
    )
    render.echo()
    render.echo(
        render.table(
            ["FEATURE", "COVERED"],
            [[feature, ("yes", "green") if met else ("no", "yellow")] for feature, met in covers],
        )
    )
    if user.locked_out:
        render.warn("the account is locked out")


@snow_app.command("token")
def token(
    ctx: typer.Context,
    profile: ProfileOption = None,
    raw: Annotated[bool, typer.Option("--raw", help="Print only the token, for piping.")] = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """Get an access token for an OAuth profile, and say how long it lasts.

    The token itself is shown only with --raw. It lasts 30 minutes by default; the kept
    refresh token renews it without asking.
    """
    runtime = get_runtime(ctx).servicenow
    selected = runtime.profile(profile)
    tokens = runtime.tokens(selected)
    access = tokens.get_token(selected.instance, "")
    if raw:
        typer.echo(access.token)
        return
    credential = runtime.credential(selected)
    kept = isinstance(credential, OAuthCredential) and credential.has_kept_sign_in()
    record = {
        "profile": selected.name,
        "instance": selected.instance,
        "expires_on": access.expires_on.isoformat(),
        "sign_in_kept": kept,
        "token_cache": selected.token_cache,
    }
    render.emit(
        output,
        ["PROFILE", "INSTANCE", "EXPIRES", "SIGN-IN KEPT"],
        [[selected.name, selected.host, render.when(access.expires_on), render.yes_no(kept)]],
        record,
    )


@snow_app.command("instance")
def instance(
    ctx: typer.Context, profile: ProfileOption = None, output: OutputOption = Output.TABLE
) -> None:
    """Show the instance's release, and whether Security Incident Response is installed.

    Exits 3 when Security Incident Response is not installed.
    """
    runtime = get_runtime(ctx).servicenow
    selected = runtime.profile(profile)
    client = runtime.instance(selected)
    release = client.release()
    sir = client.security_incident_response()
    record = {
        "profile": selected.name,
        "instance": selected.instance,
        "release": None if release is None else release.build_tag,
        "family": None if release is None else release.family,
        "security_incident_response": {
            "installed": sir.installed,
            "version": sir.version,
            "detail": sir.detail,
        },
    }
    render.emit(
        output,
        ["INSTANCE", "RELEASE", "SECURITY INCIDENT RESPONSE"],
        [
            [
                selected.host,
                "unknown" if release is None else release.label,
                ("installed" + (f" {sir.version}" if sir.version else ""), "green")
                if sir.installed
                else ("not installed", "yellow"),
            ]
        ],
        record,
    )
    if not sir.installed:
        render.note(
            "Security Incident Response is not installed. On a developer instance, activate "
            "it from developer.servicenow.com (your instance > Activate Plugin), or search "
            "for it under All > System Applications > All Available Applications."
        )
        raise typer.Exit(ATTENTION)


@snow_app.command("apps")
def apps(
    ctx: typer.Context,
    search: Annotated[
        str | None, typer.Argument(help="Part of a name or scope, e.g. 'security'.")
    ] = None,
    show_all: Annotated[
        bool, typer.Option("--all", help="Include applications that are not active.")
    ] = False,
    profile: ProfileOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """List the instance's applications (store and custom), optionally matching SEARCH.

    Security Incident Response, once installed, is listed as scope sn_si. ServiceNow
    closes its plugin tables to the API, so older plugins without a scope do not show.
    """
    runtime = get_runtime(ctx).servicenow
    selected = runtime.profile(profile)
    found = runtime.instance(selected).applications(search, active_only=not show_all)
    render.emit(
        output,
        ["NAME", "SCOPE", "KIND", "STATE", "VERSION"],
        [
            [
                app.name,
                app.scope,
                app.kind,
                ("active", "green") if app.active else ("inactive", "bright_black"),
                app.version,
            ]
            for app in found
        ],
        [dict(app.raw) for app in found],
    )
    render.note(f"{len(found)} application(s)")


# 'plugins' is what people search for; it lists the same applications.
snow_app.command("plugins", hidden=True)(apps)
