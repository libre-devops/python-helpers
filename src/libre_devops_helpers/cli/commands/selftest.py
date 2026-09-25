"""The self-test: every read-only command, run against names you choose, to find bugs.

Hidden from --help: it is for trying a build in a real tenant before a release. Each command
runs in this process with its output captured and thrown away; only what happened is kept:

- ok: it succeeded;
- attention: it exited 3, having found something, as designed;
- refused: it stopped with an error it explained, most often a missing permission or scope;
- usage: it rejected its own arguments, which is a bug in the test or the command;
- CRASH: an exception escaped, which is a bug, reported with the line of ldo it came from.

Nothing here changes anything, and no token is printed. Run it with a profile that is
already signed in: a sign-in cannot be answered while it runs.
"""

import json
import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer

from libre_devops_helpers.cli import render
from libre_devops_helpers.cli.options import (
    OutputOption,
    SortOption,
    UniqueOption,
    get_runtime,
)
from libre_devops_helpers.cli.render import Output
from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import LdoError
from libre_devops_helpers.core.util import short_name

_PACKAGE = __name__.split(".", 1)[0]
_JSON_SAMPLE = '{"value": [{"id": "1", "name": "web01", "on": true, "at": null}]}'


@dataclass(frozen=True)
class Case:
    """One command to run: its arguments, with {device}, {short}, {user}, {group},
    {workspace} and {vault} filled in, and what it needs to be worth running."""

    args: tuple[str, ...]
    needs: tuple[str, ...] = ()
    slow: bool = False
    stdin: str | None = None


@dataclass
class Outcome:
    """What one command did: its result (ok, attention, refused, usage or CRASH), its exit code and
    time, and for a failure, what it said and the lines of the package it came through."""

    command: str
    result: str
    exit_code: int | None
    seconds: float
    detail: str = ""
    hint: str | None = None
    where: list[str] = field(default_factory=list)


CASES = (
    Case(("welcome",)),
    Case(("profiles",)),
    Case(("config", "path")),
    Case(("network", "test")),
    Case(("az", "whoami")),
    Case(("json",), stdin=_JSON_SAMPLE),
    Case(("json", "--yaml"), stdin=_JSON_SAMPLE),
    Case(("entra", "token", "graph")),
    Case(("entra", "token", "mde")),
    Case(("entra", "token", "arm")),
    Case(("graph", "whoami")),
    Case(("graph", "get", "me")),
    Case(("graph", "get", "organization", "--select", "id,displayName")),
    Case(("entra", "ca-policies")),
    Case(("entra", "sign-ins", "--since", "1d", "--limit", "5")),
    Case(("entra", "app-credentials", "--expiring", "30d"), slow=True),
    Case(("graph", "get-device", "{device}"), ("device",)),
    Case(("entra", "devices", "{device}"), ("device",)),
    Case(("entra", "devices", "{short}"), ("device",)),
    Case(("entra", "device-groups", "{device}"), ("device",)),
    Case(("xdr", "machines", "{device}"), ("device",)),
    Case(("xdr", "machines", "{short}"), ("device",)),
    Case(
        ("xdr", "machines", "{short}", "--sort", "last seen:desc", "--unique", "device"),
        ("device",),
    ),
    Case(("xdr", "alerts", "--device", "{device}", "--include-resolved"), ("device",)),
    Case(("xdr", "vulns", "{device}"), ("device",)),
    Case(("xdr", "timeline", "{device}", "--since", "1h", "--endpoint"), ("device",)),
    Case(
        ("xdr", "timeline", "{device}", "--since", "1h", "--type", "process,network"), ("device",)
    ),
    Case(
        ("xdr", "vulns", "{device}", "--sort", "severity:desc", "--sort", "cvss:desc"), ("device",)
    ),
    Case(("devices", "check", "{device}"), ("device",)),
    Case(("devices", "show", "{device}"), ("device",)),
    Case(("devices", "av-signature", "{device}", "--endpoint"), ("device",)),
    Case(("devices", "av-signature", "{device}"), ("device",)),
    Case(("intune", "devices", "{device}"), ("device",)),
    Case(("graph", "get-group", "{group}"), ("group",)),
    Case(("entra", "devices", "{device}", "--group", "{group}"), ("device", "group")),
    Case(("devices", "check", "{device}", "--group", "{group}"), ("device", "group")),
    Case(("entra", "group-devices", "{group}"), ("group",), slow=True),
    Case(("graph", "get-user", "{user}"), ("user",)),
    Case(("entra", "user-groups", "{user}"), ("user",)),
    Case(("entra", "user-roles", "{user}"), ("user",)),
    Case(("entra", "sign-ins", "--user", "{user}", "--since", "7d", "--limit", "5"), ("user",)),
    Case(("azure", "rbac", "{user}"), ("user",), slow=True),
    Case(("xdr", "alerts", "--since", "24h", "--limit", "5")),
    Case(("xdr", "alerts", "--since", "7d", "--sort", "severity:desc", "--unique", "title")),
    Case(("xdr", "indicators")),
    Case(("xdr", "detections", "list")),
    Case(("xdr", "stale", "--older-than", "180d"), slow=True),
    Case(("xdr", "hunt", "DeviceInfo | take 1", "--endpoint")),
    Case(("xdr", "hunt", "DeviceInfo | take 1")),
    Case(("xdr", "incidents", "top")),
    Case(("xdr", "incidents", "summary", "--since", "1d")),
    Case(("azure", "subscriptions")),
    Case(("azure", "resource-graph", "resources | take 1")),
    Case(("azure", "secure-score")),
    Case(("azure", "defender-plans")),
    Case(("azure", "recommendations", "--severity", "high"), slow=True),
    Case(("azure", "automation", "accounts")),
    # Only a vault named: a request to every vault in the tenant, refused and logged by each
    # one the person cannot read, looks like reconnaissance to Defender for Key Vault.
    Case(("keyvault", "expiry", "{vault}", "--within", "30d"), ("vault",)),
    Case(("logs", "query", "Heartbeat | take 1", "--workspace", "{workspace}"), ("workspace",)),
    Case(("logs", "ingestion", "--workspace", "{workspace}"), ("workspace",)),
    Case(("pim", "eligible", "--azure")),
    Case(("pim", "active", "--azure")),
    Case(("pim", "eligible")),
    Case(("snow", "whoami"), ("snow",)),
    Case(("snow", "instance"), ("snow",)),
)


def register(app: typer.Typer) -> None:
    """Add the hidden ``self-test`` command to ``app``."""
    app.command("self-test", hidden=True)(self_test)


def self_test(
    ctx: typer.Context,
    device: Annotated[
        str | None, typer.Option("--device", help="A device to look up: its FQDN is best.")
    ] = None,
    user: Annotated[str | None, typer.Option("--user", help="A user's UPN to look up.")] = None,
    group: Annotated[
        str | None, typer.Option("--group", help="An Entra group, by display name or object id.")
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help="A Log Analytics workspace: its Workspace ID, its resource id or its name.",
        ),
    ] = None,
    vault: Annotated[
        str | None,
        typer.Option("--vault", help="A Key Vault you can read, for keyvault expiry."),
    ] = None,
    snow: Annotated[
        bool, typer.Option("--snow", help="Also test the ServiceNow commands.")
    ] = False,
    everything: Annotated[
        bool, typer.Option("--all", help="Also run the slow ones (whole-tenant listings).")
    ] = False,
    only: Annotated[
        list[str] | None,
        typer.Option("--only", help="Only commands starting with this, e.g. xdr. Repeatable."),
    ] = None,
    profile: Annotated[
        str | None, typer.Option("--profile", "-p", help="The profile every command uses.")
    ] = None,
    report: Annotated[
        Path | None,
        typer.Option("--report", help="Also write every outcome, and where each crash was, here."),
    ] = None,
    sort: SortOption = None,
    unique: UniqueOption = None,
    output: OutputOption = Output.TABLE,
) -> None:
    """Run every read-only command against the names given, and report what broke.

    Output is thrown away; only each command's outcome is shown: ok, attention (exit 3, as
    designed), refused (an explained error, often a permission), usage, or CRASH (a bug,
    with the line of ldo it came from). After the table, each failure is shown in full with
    its hint. Exits 1 when anything crashed.
    """
    names = {
        "device": device,
        "short": short_name(device) if device else None,
        "user": user,
        "group": group,
        "workspace": workspace,
        "vault": vault,
        "snow": "yes" if snow else None,
    }
    chosen = [
        case
        for case in CASES
        if all(names.get(need) for need in case.needs)
        and (everything or not case.slow)
        and (not only or any(" ".join(case.args).startswith(prefix) for prefix in only))
    ]
    filled = {key: value or "" for key, value in names.items()}
    # Filled in, a short --device makes {device} and {short} the same: run it once.
    runs = list(
        dict.fromkeys(
            (tuple(part.format(**filled) for part in case.args), case.stdin) for case in chosen
        )
    )
    config_path = get_runtime(ctx).config_path
    render.note(f"running {len(runs)} commands; each one's output is discarded")
    skipped, flags = _left_out(names, everything=everything, only=only)
    if skipped:
        render.note(f"{skipped} more need {', '.join(flags)}: give them to run those too")
    outcomes: list[Outcome] = []
    try:
        for number, (args, stdin) in enumerate(runs, 1):
            outcome = _run(list(args), stdin, config_path, profile)
            outcomes.append(outcome)
            render.note(
                f"{number:>{len(str(len(runs)))}}/{len(runs)}  {outcome.result:<9}  "
                f"{brand.COMMAND} {outcome.command}"
            )
    except KeyboardInterrupt:
        render.warn(f"stopped after {len(outcomes)} of {len(runs)}")
    _show(outcomes, output)
    if report is not None:
        report.write_text(json.dumps([vars(item) for item in outcomes], indent=2) + "\n", "utf-8")
        render.note(f"wrote {report}")
    counts = {name: sum(1 for item in outcomes if item.result == name) for name in _RESULTS}
    render.note(", ".join(f"{count} {name}" for name, count in counts.items() if count))
    if counts["CRASH"] or counts["usage"]:
        raise typer.Exit(1)


_RESULTS = ("ok", "attention", "refused", "usage", "CRASH")


def _run(args: list[str], stdin: str | None, config: Path | None, profile: str | None) -> Outcome:
    """One command, in this process, with its output captured and dropped."""
    from typer.testing import CliRunner

    from libre_devops_helpers.cli.app import app

    command = " ".join(args)
    full = [*(["--config", str(config)] if config else []), *args]
    previous = os.environ.get(brand.PROFILE_ENV)
    if profile:
        os.environ[brand.PROFILE_ENV] = profile
    started = time.monotonic()
    try:
        result = CliRunner().invoke(app, full, input=stdin, catch_exceptions=True)
    finally:
        if profile:
            if previous is None:
                os.environ.pop(brand.PROFILE_ENV, None)
            else:
                os.environ[brand.PROFILE_ENV] = previous
    seconds = round(time.monotonic() - started, 2)
    error = result.exception
    if error is None or isinstance(error, SystemExit):
        code = result.exit_code
        if code == 0:
            return Outcome(command, "ok", code, seconds)
        if code == 3:
            return Outcome(command, "attention", code, seconds, "exit 3: a finding, as designed")
        if code == 2:
            return Outcome(command, "usage", code, seconds, _last_line(result.output))
        said, hint = _explanation(result.output)
        return Outcome(command, "refused", code, seconds, said, hint)
    if isinstance(error, LdoError):
        return Outcome(command, "refused", 1, seconds, str(error), error.hint)
    frames = traceback.extract_tb(error.__traceback__)
    ours = [
        f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}"
        for frame in frames
        if _PACKAGE in frame.filename
    ]
    return Outcome(
        command, "CRASH", None, seconds, f"{type(error).__name__}: {error}", None, ours[-3:]
    )


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


def _explanation(text: str) -> tuple[str, str | None]:
    """Why a command that exited 1 without an error of ours stopped: every error and
    warning it wrote, one a line, and their hints. Its last line alone is often only its
    summary (a count of what it read), with the reason in a warning above it."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    said = list(dict.fromkeys(line for line in lines if line.startswith(("error:", "warning:"))))
    hints = list(dict.fromkeys(line[5:].strip() for line in lines if line.startswith("hint:")))
    if not said:
        return _last_line(text), None
    return "\n".join(said), "\n".join(hints) or None


# The option that gives each name a case can need.
_NAME_OPTIONS = {
    "device": "--device",
    "short": "--device",
    "user": "--user",
    "group": "--group",
    "workspace": "--workspace",
    "vault": "--vault",
    "snow": "--snow",
}


def _left_out(
    names: dict[str, str | None], *, everything: bool, only: list[str] | None
) -> tuple[int, list[str]]:
    """How many cases were left out for want of a name, and the options that give them."""
    skipped = 0
    options: set[str] = set()
    for case in CASES:
        wanted = (everything or not case.slow) and (
            not only or any(" ".join(case.args).startswith(prefix) for prefix in only)
        )
        missing = [need for need in case.needs if not names.get(need)]
        if wanted and missing:
            skipped += 1
            options.update(_NAME_OPTIONS[need] for need in missing)
    return skipped, sorted(options)


def _show(outcomes: list[Outcome], output: Output) -> None:
    colours = {
        "ok": "green",
        "attention": "yellow",
        "refused": "yellow",
        "usage": "red",
        "CRASH": "red",
    }
    rows: list[list[render.Cell]] = []
    for item in outcomes:
        first, *more = item.detail.splitlines() or [""]
        detail = f"{first} (and {len(more)} more)" if more else first
        if item.where:
            detail += f" (at {item.where[-1]})"
        rows.append(
            [item.command, (item.result, colours[item.result]), f"{item.seconds:.1f}s", detail]
        )
    records: list[dict[str, Any]] = [vars(item) for item in outcomes]
    render.emit(output, ["COMMAND", "RESULT", "TIME", "DETAIL"], rows, records)
    if output is Output.TABLE:
        _show_details(outcomes)


def _show_details(outcomes: list[Outcome]) -> None:
    """Each failure in full, since the table cuts DETAIL short when commands are long: what
    it said, its hint, and for a crash, the lines of the package it came through."""
    failed = [item for item in outcomes if item.result in {"refused", "usage", "CRASH"}]
    for item in failed:
        render.echo()
        render.echo(render.title(f"{item.result}: {brand.COMMAND} {item.command}"))
        lines = [("Said", said) for said in item.detail.splitlines() or [""]]
        lines += [("Hint", hint) for hint in (item.hint or "").splitlines() or [""]]
        lines += [("At", where) for where in item.where]
        render.echo(render.pairs(lines))
