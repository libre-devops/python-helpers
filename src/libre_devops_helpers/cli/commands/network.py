"""Network commands: test the way out, through the proxy and past a TLS-inspecting one.

``network test`` asks each service ldo uses for something every one answers without a
sign-in, and expects a 2xx: proof the proxy, the certificates and the route all work, the
same way every other command's calls go.
"""

from dataclasses import dataclass
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.exits import ATTENTION
from libre_devops_helpers.cli.options import (
    OutputOption,
    ProfileOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core import network
from libre_devops_helpers.core.errors import ConfigError, LdoError
from libre_devops_helpers.core.probe import Probe, probe_all
from libre_devops_helpers.microsoft.clouds import PUBLIC, Cloud

network_app = typer.Typer(
    rich_markup_mode="markdown",
    help="The network: test the proxy, the certificates and the way to each service.",
    no_args_is_help=True,
)

_OK = range(200, 300)


@dataclass(frozen=True)
class Endpoint:
    """A service to try: its name, a URL it answers without a sign-in, the statuses that mean it was
    reached, and a note to show beside a pass."""

    name: str
    url: str
    expect: tuple[int, ...] = tuple(_OK)
    note: str = ""


def register(app: typer.Typer) -> None:
    """Add the ``network`` commands to ``app``."""
    app.add_typer(network_app, name="network")


@network_app.command("test")
def network_test(
    ctx: typer.Context,
    url: Annotated[
        list[str] | None,
        typer.Option("--url", help="Also test this https URL, expecting a 2xx. Repeatable."),
    ] = None,
    timeout: Annotated[
        float, typer.Option("--timeout", min=1, max=120, help="Seconds to wait for each.")
    ] = 10.0,
    profile: ProfileOption = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Test the way out to each service: the proxy, the certificates and the route.

    Asks Entra ID, Graph, Azure Resource Manager and Defender (in the profile's cloud), and
    each ServiceNow instance configured, for something they answer without a sign-in, the
    same way every other call goes. Says which proxy each went through and, when one fails,
    what to try. Exits 3 when any fails.
    """
    runtime = get_runtime(ctx)
    endpoints = _endpoints(runtime, profile) + [
        Endpoint(item, item) for item in _checked_urls(url or [])
    ]
    settings = _settings()
    probes = probe_all([(item.url, item.expect) for item in endpoints], timeout=timeout)
    results = list(zip(endpoints, probes, strict=True))
    if output is Output.TABLE:
        render.echo(render.pairs(settings["pairs"]))
        render.echo()
    render.emit(
        output,
        ["ENDPOINT", "VIA", "RESULT", "DETAIL"],
        [_probe_row(endpoint, result) for endpoint, result in results],
        {
            "settings": settings["record"],
            "endpoints": [_probe_record(endpoint, result) for endpoint, result in results],
        },
    )
    failed = [(endpoint, result) for endpoint, result in results if not result.ok]
    for endpoint, result in failed:
        if result.hint:
            render.warn(f"{endpoint.name}: {result.hint}")
    render.note(f"{len(endpoints) - len(failed)} of {len(endpoints)} reachable")
    if failed:
        raise typer.Exit(ATTENTION)


def _probe_row(endpoint: Endpoint, result: Probe) -> list[render.Cell]:
    """ENDPOINT, VIA (the proxy, without its password, or direct), RESULT, DETAIL."""
    if result.route.proxy is None and result.route.source in {"none", "local"}:
        via = "direct"
    else:
        via = result.route.shown or f"direct ({result.route.source})"
    detail = result.detail
    if result.ok:
        detail += f" in {result.elapsed:.2f}s" + (f" ({endpoint.note})" if endpoint.note else "")
    return [endpoint.name, via, ("ok", "green") if result.ok else ("failed", "red"), detail]


def _probe_record(endpoint: Endpoint, result: Probe) -> dict[str, Any]:
    return {
        "name": endpoint.name,
        "url": endpoint.url,
        "proxy": result.route.shown,
        "route": result.route.source,
        "ok": result.ok,
        "status": result.status,
        "detail": result.detail,
        "hint": result.hint,
        "seconds": result.elapsed,
    }


def _endpoints(runtime: Runtime, profile_name: str | None) -> list[Endpoint]:
    cloud, mde_url = _cloud(runtime, profile_name)
    found = [
        Endpoint(
            "Entra ID sign-in",
            f"{cloud.login_url.rstrip('/')}/common/v2.0/.well-known/openid-configuration",
        ),
        Endpoint("Microsoft Graph", f"{cloud.graph_url.rstrip('/')}/v1.0/"),
        Endpoint(
            "Azure Resource Manager",
            f"{cloud.arm_url.rstrip('/')}/metadata/endpoints?api-version=2022-09-01",
        ),
    ]
    defender = mde_url or cloud.mde_url
    if defender:
        # The Defender API has nothing to show without a token; its 401 proves the way in.
        found.append(
            Endpoint(
                "Defender for Endpoint",
                f"{defender.rstrip('/')}/api/",
                (*_OK, 401),
                "401 without a token is the expected answer",
            )
        )
    for url in _servicenow_instances(runtime):
        found.append(
            Endpoint(
                f"ServiceNow {url.removeprefix('https://')}", f"{url}/", (*_OK, *range(300, 400))
            )
        )
    return found


def _cloud(runtime: Runtime, profile_name: str | None) -> tuple[Cloud, str | None]:
    """The profile's cloud when there is one to go on; the public cloud otherwise."""
    microsoft = runtime.microsoft
    try:
        if profile_name:
            chosen = microsoft.profile(profile_name)
            return chosen.cloud, chosen.mde_url
        config = microsoft.optional_config()
        if config is not None and config.default_profile:
            chosen = config.get(config.default_profile)
            return chosen.cloud, chosen.mde_url
    except ConfigError as exc:
        render.warn(f"testing the public cloud: {exc}")
    return PUBLIC, None


def _servicenow_instances(runtime: Runtime) -> list[str]:
    try:
        profiles = runtime.servicenow.profiles()
    except LdoError:
        return []
    return list(dict.fromkeys(profile.instance for profile in profiles))


def _checked_urls(urls: list[str]) -> list[str]:
    for item in urls:
        if not item.startswith("https://"):
            raise typer.BadParameter(f"{item!r} is not an https URL", param_hint="--url")
    return urls


def _settings() -> dict[str, Any]:
    proxy = network.configured()
    bundle = network.ca_bundle()
    skipped = list(dict.fromkeys([*network.ALWAYS_DIRECT, *network.no_proxy()]))
    if bundle.explicit:
        trust = f"{bundle.path}, used as it is ({bundle.explicit})"
    else:
        trust = (
            f"{bundle.path}: {bundle.public} public, {bundle.system} from this machine's "
            f"store, {bundle.extra} from ca_bundle"
        )
    return {
        "pairs": [
            ("Proxy", f"{proxy.shown} ({proxy.source})" if proxy.proxy else "none: direct"),
            ("No proxy", ", ".join(skipped)),
            ("Certificates", trust),
        ],
        "record": {
            "proxy": proxy.shown,
            "proxy_source": proxy.source,
            "no_proxy": skipped,
            "ca_bundle": bundle.path,
            "ca_bundle_source": bundle.explicit or "combined",
            "certificates": {
                "public": bundle.public,
                "system": bundle.system,
                "extra": bundle.extra,
            },
        },
    }
