<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# Instructions for AI coding assistants

This file is for Claude Code, GitHub Copilot, OpenAI Codex and any other assistant working
in this repository. It is the one to edit: `AGENTS.md` is generated from it (`just ai`),
`CLAUDE.md` imports it, and `.github/copilot-instructions.md` points here.

## What this is

`ldo` (distribution `libre-devops-helpers`, import `libre_devops_helpers`): a fast, read-only
CLI and library for Microsoft (Entra ID, Defender XDR, Intune, Azure, Graph, PIM, Logic Apps,
Automation) and ServiceNow. Its users are people signing in as themselves, usually through
the Azure CLI; automation is second. Everything reads, apart from `ldo az use`, which switches
the Azure CLI's account. Never add a command that changes a tenant or an instance without
being asked.

## Working here

- Run everything through `just` (or `uv run`): `just check` before calling anything done,
  `just ci` for all of CI's checks, `just fmt` to format, `just run <args>` to try the CLI.
- Python 3.11 or later: nothing newer than 3.11 in the code (`just test-311` proves it).
- ruff, line length 100. Match the surrounding code's naming, comment density and idiom.
- Runtime dependencies are `requests` and `typer` only. Everything else is the standard
  library. Do not add a runtime dependency without asking; test-only ones go in the `dev`
  group.

## Layout and layering

```text
src/libre_devops_helpers/
  core/                 vendor-neutral: errors, config, brand, HTTP client, token store,
                        polling, inputs (CSV and Excel), logging, YAML writer
  microsoft/            the shared Microsoft layer: clouds, credentials, tokens, profiles
  microsoft/<feature>/  one package per API: entra, xdr, graph, azure, pim, automation ...
  microsoft/devices/    the one composite, using entra, xdr and intune
  servicenow/           the ServiceNow vendor, same shape
  cli/                  the ldo command: parses, calls a client, renders. No logic here.
```

`tests/project/test_package_surface.py` enforces the layering: `core` imports nothing of
ours, a feature imports only `core` and its vendor layer, `cli` sits on top. Cross-cutting
code (auth, HTTP, input parsing) goes in `core` or the vendor layer, never in a feature. A new
feature package needs its entry in that test, a `REQUIREMENTS` tuple, and a test folder.

## Tests

- Tests mirror `src` (`tests/core`, `tests/microsoft/<feature>`, `tests/cli/commands`), one
  test module per module, and `tests/project/test_layout.py` checks it.
- Nothing touches the network, a real `az` or a real clock. HTTP goes through
  `tests/fakes/http.py` (`routes`, `fake_session`), `az` through `fakes/azcli.py`, time
  through `fakes/clock.py`. Shared fakes live in `tests/fakes`, one module per concern.
- Coverage is gated at 93% (`fail_under` in `pyproject.toml`). Keep new code covered.
- CI runs with `GITHUB_ACTIONS` set, which makes Typer colour and wrap errors: compare error
  text with `usage_error(result)`, never a raw substring of `result.output`.
- Windows caps an environment variable at 32,767 characters and pytest puts each test id in
  one: give big parametrised values short `ids`.
- `tests/project/test_rebrand.py` renames a copy of the repository and runs its whole suite.

## Names and branding

The project can be renamed (`just rebrand`). Never hard-code `ldo`, `LDO_` or the package
name in code: use `core/brand.py` (`brand.COMMAND`, `brand.env_var("X")`,
`brand.command("config init")`, `brand.docs("page")` for a link to a docs page).

## Writing code

- Library code raises `LdoError` subclasses (`InputError`, `NotFoundError`,
  `AmbiguousError`, `ApiError`, ...) with a `hint` saying what to do, and never exits. Only
  the CLI turns errors into messages and exit codes (0 fine, 1 error, 2 usage, 3 needs
  attention, 130 interrupted).
- Data goes to stdout; notes, warnings and progress to stderr, through `cli/render.py`
  (`note`, `warn`, `error`, `emit`). In the `json` and `otlp` log formats those become log
  records, so never write to stderr directly.
- Every data command takes `-o table|json|csv` and `-p PROFILE`; lists of names take
  arguments, `-` for stdin and `-f FILE` with `--column` and `--sheet`.
- All HTTP goes through `core.http.ApiClient`, which applies `core/network.py` (the proxy
  and `no_proxy`) and `core/trust.py` (the public roots, the OS store and `ca_bundle`), and
  `az` runs with the same through `network.subprocess_env()`. Never call `requests` directly.
- Anything a person types that goes into a URL path or a query is validated first (names,
  ids, KQL values). A token or secret is never printed (only with an explicit `--raw`), never
  logged, and never accepted on the command line.
- Help text is rendered as markdown: no `<`, no `*`, and paragraphs reflow. A test checks.
- Do not hide findings from a scanner or linter by renaming things; fix the code, or say it
  is a false positive and why.

## Docs

- `README.md` is a short front page: the command table, install, quickstart and links.
  Detail goes in `docs/`, one page per area. `CHANGELOG.md` gets an `Unreleased` entry for
  every change a user would notice.
- `tests/project/test_docs.py` runs every `ldo` example in the README, `docs/` and this file
  with `--help`, checks every `just` example is a recipe, and follows every link. Keep
  examples real.
- UK English (colour, organisation, licence as a noun). Never use em or en dashes, in any
  file: use commas, colons, brackets or a plain hyphen.

## Commits and releases

- Do not commit, push, tag or release until the person asks. Use their own git identity.
- No AI attribution in commits or pull requests: no `Co-Authored-By` or "Generated with"
  lines.
- A release is `just release` after the version is set in `pyproject.toml` and
  `src/libre_devops_helpers/__init__.py` and `CHANGELOG.md` has its section; see
  `docs/development.md`. Never move or reuse a released tag, and remember a PyPI version can
  never be replaced.

## Pitfalls already met

- `.gitignore` rules match anywhere unless anchored with `/`; ruff and hatchling honour
  `.gitignore`, so an ignored folder is silently left out of linting and the wheel.
- The arm64 image is built under emulation: keep heavy work (such as compiling bytecode) in
  a `FROM --platform=$BUILDPLATFORM` stage.
- The Azure CLI pins some dependencies exactly. A fix it holds back is forced in
  `container/azure-cli/pyproject.toml` (see the comment there), then signed in with.
- Microsoft APIs return stale duplicates (devices share names), paginate with `nextLink`
  or `@odata.nextLink`, and answer 403 for a missing scope and a suspended tenant alike: say
  which in the hint.
