# Contributing to libre-devops-helpers

Contributions are welcome, whether that is reporting an issue, proposing a fix, suggesting a
command or improving the documentation.

## Workflow

1. Fork the repository and branch from `main`.
2. Run `just sync` (or `uv sync`) to create the environment.
3. Make your change, with tests.
4. Run `just check`. It must pass: ruff lint, ruff format check, and the tests with
   coverage at or above the floor in `pyproject.toml`. `just ci` runs everything else CI
   checks too: Python 3.11, the dependency audit and the build.
5. Open a pull request using the template. CI then also scans every commit for secrets
   (gitleaks), audits the locked dependencies (pip-audit), runs the tests on Python 3.11 to
   3.14 and on Windows and macOS, measures coverage, builds the wheel, and builds, runs
   and scans both container images. All of it must pass to merge.

Security issues are the exception: report those privately, as described in
[SECURITY.md](SECURITY.md).

## Code standards

The [Libre DevOps Python standards](https://libredevops.org/docs/documents/python-standards)
are the general reference. The rules that matter most here:

1. Target Python 3.11 or later. Type-hint every public function.
2. Keep the layering, which `tests/project/test_package_surface.py` enforces:
   - `core` is vendor-neutral: errors, the config file, the brand, the token cache, the HTTP
     client, the command runner, polling, input parsing, query results and logging. It
     depends on nothing else in the package. Put a shared helper here rather than copying it
     into a second module.
   - Each vendor has a shared layer for what all of its features need: for Microsoft,
     `microsoft/*.py` and `microsoft/auth` (clouds, credentials, CLI runners, token checks,
     its config section); for ServiceNow, `servicenow/*.py` (its config section,
     credentials, the Table API client, role requirements).
   - Each feature module (`microsoft/entra`, `microsoft/xdr`, ...) depends on `core` and its
     vendor's shared layer only, and declares the token scopes its calls need in
     `REQUIREMENTS`.
   - A composite module (`microsoft/devices`) may also use the features it combines.
   - `cli` sits on top of everything, and nothing imports it.
3. Library code raises `LdoError` subclasses and never exits the process. Only the `cli`
   package turns errors into messages and exit codes.
4. Everything is read-only apart from `az use`. A new command that writes to a tenant or an
   instance needs discussion in an issue first. Secrets are read from the environment, never
   the config file.
5. Never log or print an access token. `AccessToken` keeps the value out of its `repr`; keep
   it that way.
6. Library modules log through `logging.getLogger(__name__)` with lazy `%s` formatting, and
   never configure handlers.
7. Data goes to stdout, and notes, warnings and errors go to stderr, so output can be piped.
8. Keep runtime dependencies to `requests` and `typer`. Anything else needs a good reason.
9. Everything must be testable, and tests must not touch the network, a real `az` or a real
   clock. Inject the session, subprocess runner, environment, clock and sleep, and use the
   fakes in `tests/fakes`: `fakes.http` (a fake `requests` adapter, and `routes` for a few
   endpoints), `fakes.azcli` (a fake Azure CLI), `fakes.clock` (a clock for anything that
   polls), `fakes.workbooks` (Excel files built by hand) and the rest. Run `just test-311`
   as well as `just check`, so nothing newer than Python 3.11 slips in.
10. Never hard-code the tool's names. The command, environment variable prefix, config
    directory, display name and banner come from `core/brand.py`, so `just rebrand` can
    rename everything; `tests/project/test_rebrand.py` rebrands a copy and runs its suite to prove it.
11. Use UK English and plain ASCII in code, comments and docs: no smart quotes, em or en
    dashes, or ellipsis glyphs.
12. Never include real tokens, tenant ids, subscription ids or host names in code, tests or
    issues. Use the placeholder GUIDs and `example.com` names the tests already use. If
    gitleaks flags a public value the code needs, add the narrowest pattern you can to
    `.gitleaks.toml` and say why in the pull request; never widen it to a whole file.
13. Put tests where the code is: `tests/<path>/test_<module>.py` for
    `src/libre_devops_helpers/<path>/<module>.py`. A new subpackage needs a matching test
    directory, and `tests/project/test_layout.py` fails until it has one. Share helpers
    through a module in `tests/fakes`, never by importing another test module.
14. Keep coverage up. `just coverage` shows what a change leaves untested; raise
    `fail_under` in `pyproject.toml` when coverage grows, and never lower it to get a
    change in.
15. The container images must keep working as an unprivileged user with a read-only
    `/work`. `just image`, `just image-slim` and `just image-scan` run what CI runs.

When you add a command, option or exit code, document it on its page in `docs/` (and in the
README's command table for a new group), and in `CHANGELOG.md`, in the same pull request. A
test runs every example in the docs with `--help` and follows every link, so a renamed
command or option shows up there.

## Licence

By contributing, you agree that your contributions are licensed under the
[MIT Licence](LICENSE) that covers the project.
