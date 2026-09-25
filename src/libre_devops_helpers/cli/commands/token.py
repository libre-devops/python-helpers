"""Token commands: get a token for a profile, inspect one you have, or forget a sign-in."""

import json
import sys
from dataclasses import asdict
from typing import Annotated

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ERROR
from libre_devops_helpers.cli.options import OutputOption, ProfileOption, get_runtime
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import ConfigError, InputError
from libre_devops_helpers.microsoft import detections, entra, graph, incidents, intune, pim, xdr
from libre_devops_helpers.microsoft.resources import resolve_resource
from libre_devops_helpers.microsoft.tokens import (
    Check,
    DecodedToken,
    decode_token,
    passed,
    validate_token,
)

# Every feature module declares what its calls need; the token checks report each one.
REQUIREMENTS = (
    *entra.REQUIREMENTS,
    *xdr.REQUIREMENTS,
    *intune.REQUIREMENTS,
    *pim.REQUIREMENTS,
    *incidents.REQUIREMENTS,
    *detections.REQUIREMENTS,
    *graph.REQUIREMENTS,
)

RequireOption = Annotated[
    list[str] | None,
    typer.Option("--require", help="Scope or role the token must carry. Repeatable."),
]
StrictOption = Annotated[bool, typer.Option("--strict", help="Treat warnings as failures.")]
AllClaimsOption = Annotated[
    bool, typer.Option("--all-claims", help="Show every claim, not only the summary.")
]


def register(app: typer.Typer) -> None:
    """Add ``token``, ``inspect-token`` and ``sign-out`` to ``app`` (the ``entra`` group)."""
    app.command("token")(token)
    app.command("inspect-token")(inspect_token)
    app.command("sign-out")(sign_out)


def sign_out(ctx: typer.Context, profile: ProfileOption = None) -> None:
    """Forget the sign-in an interactive or device-code profile keeps (see token_cache).

    The refresh token is removed from the keychain or file; the next command signs in
    afresh. Signing out of Entra ID itself, everywhere, is done in your account settings.
    """
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    if selected.auth == "azure-cli":
        raise ConfigError(
            f"profile {selected.name!r} uses the Azure CLI's sign-in, which it keeps itself",
            hint="run 'az logout', or 'az account clear' to forget every account",
        )
    if selected.token_cache == "memory":
        render.note(f'profile {selected.name!r} keeps no sign-in (token_cache = "memory")')
        return
    if runtime.sign_out(selected):
        render.note(f"Forgot the sign-in kept for {selected.name} ({selected.token_cache}).")
    else:
        render.note(f"No sign-in was kept for {selected.name}.")


def token(
    ctx: typer.Context,
    resource: Annotated[
        str,
        typer.Argument(help="graph, mde, arm, loganalytics, keyvault, or a resource URL."),
    ],
    profile: ProfileOption = None,
    raw: Annotated[
        bool, typer.Option("--raw", help="Print only the token, for piping. Still checked first.")
    ] = False,
    require: RequireOption = None,
    strict: StrictOption = False,
    all_claims: AllClaimsOption = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """Get an access token with the profile's credential and check its claims.

    Exits 1 when a check fails (or warns, with --strict). The token itself is printed
    only with --raw.
    """
    runtime = get_runtime(ctx).microsoft
    selected = runtime.profile(profile)
    target = resolve_resource(resource, selected.cloud)
    access = runtime.tokens(selected).get_token(target.url, selected.tenant_id)
    decoded = decode_token(access.token)
    checks = validate_token(
        decoded,
        resource=target,
        tenant_id=selected.tenant_id,
        required=require or (),
        requirements=REQUIREMENTS,
    )
    ok = passed(checks, strict=strict)
    if raw:
        if not ok:
            render.checks_to_stderr(checks)
            raise typer.Exit(ERROR)
        render.echo(access.token)
        return
    _report(
        decoded,
        checks,
        heading=f"{target.key} token for profile {selected.name} ({selected.auth})",
        all_claims=all_claims,
        output=output,
        ok=ok,
    )
    if not ok:
        raise typer.Exit(ERROR)


def inspect_token(
    value: Annotated[
        str | None,
        typer.Argument(
            metavar="[TOKEN]",
            help="Token to inspect. Omit or pass - to read stdin (keeps it out of shell history).",
            show_default=False,
        ),
    ] = None,
    resource: Annotated[
        str | None,
        typer.Option("--resource", help="Expected API: graph, mde, arm, ..., or a URL."),
    ] = None,
    tenant: Annotated[str | None, typer.Option("--tenant", help="Expected tenant id.")] = None,
    require: RequireOption = None,
    strict: StrictOption = False,
    all_claims: AllClaimsOption = False,
    output: OutputOption = Output.TABLE,
) -> None:
    """Decode a token you already have and check its claims. Nothing is sent anywhere."""
    if value is None or value == "-":
        if sys.stdin.isatty():
            raise InputError(
                "no token given",
                hint=f"pipe one in, e.g. 'pbpaste | {brand.COMMAND} entra inspect-token'",
            )
        value = sys.stdin.read()
        if not value.strip():
            raise InputError("no token on stdin")
    decoded = decode_token(value)
    checks = validate_token(
        decoded,
        resource=resolve_resource(resource) if resource else None,
        tenant_id=tenant,
        required=require or (),
        requirements=REQUIREMENTS,
    )
    ok = passed(checks, strict=strict)
    _report(decoded, checks, heading="token", all_claims=all_claims, output=output, ok=ok)
    if not ok:
        raise typer.Exit(ERROR)


def _report(
    decoded: DecodedToken,
    checks: list[Check],
    *,
    heading: str,
    all_claims: bool,
    output: Output,
    ok: bool,
) -> None:
    if output is Output.JSON:
        render.print_json(
            {
                "valid": ok,
                "checks": [asdict(check) for check in checks],
                "header": dict(decoded.header),
                "claims": dict(decoded.claims),
            }
        )
        return
    if output in (Output.CSV, Output.TSV):
        render.emit(
            output,
            ["RESULT", "CHECK", "DETAIL"],
            [[check.status, check.name, check.detail] for check in checks],
            None,
        )
        return
    app_name = str(decoded.claims.get("app_displayname") or "")
    render.echo(render.title(heading))
    render.echo(
        render.pairs(
            [
                ("Audience", ", ".join(decoded.audiences)),
                ("Tenant", decoded.tenant_id),
                ("Issuer", decoded.issuer),
                ("Principal", f"{decoded.principal} ({decoded.identity_type})"),
                ("Client app", f"{app_name} {decoded.app_id}".strip()),
                ("Scopes (scp)", " ".join(decoded.scopes)),
                ("Roles", " ".join(decoded.roles)),
                ("Issued", render.when(decoded.issued_at)),
                ("Expires", render.when(decoded.expires_at)),
            ]
        )
    )
    if all_claims:
        render.echo()
        render.echo(
            render.pairs(
                (name, value if isinstance(value, str) else json.dumps(value))
                for name, value in sorted(decoded.claims.items())
            )
        )
    render.echo()
    render.echo(render.checks_table(checks))
    render.note("Signature not verified: this checks the claims only.")
