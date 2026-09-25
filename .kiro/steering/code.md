---
inclusion: fileMatch
fileMatchPattern: ["src/**/*.py", "tests/**/*.py", "scripts/**/*.py"]
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# Writing code

- Write for the next person to read it. No function past ruff's complexity limit of 10:
  split it into named steps. A public module, class or function gets a docstring saying what
  it gives (ruff checks); a comment says why, where the code cannot. Prefer a plain loop to
  a clever comprehension, and a named helper to a nested lambda.
- A new API client subclasses `GraphServiceClient` or `ArmServiceClient`
  (`microsoft/api_clients.py`), which give it `create`, `for_profile`, `close` and `with`,
  or `core.http.ServiceClient` for any other API. A model reads its JSON through
  `core.fields` (`text`, `mapping`, `items`, `flag`, `number`, `when`), and an id that goes
  into a path through `core.util.require_guid`.
- Raise the specific error: `InputError` for something given that cannot be used,
  `ConfigError` for a profile that cannot do this, `NotFoundError`, `AmbiguousError`,
  `AuthError`, `ApiError`; `ValueError` for a library caller's own mistake. Never the bare
  `LdoError` (a test checks).
- `-o json` is a contract with scripts: snake_case keys, real booleans and numbers, and
  `tests/project/test_json_output.py` records every command's shape. A change that is meant
  is recorded with `LDO_RECORD_JSON_OUTPUT=1` and goes in the changelog.
- mypy runs strictly on the package. Fix a type error rather than silencing it; a `cast`
  or an ignore needs a comment saying why the types are wrong and the code is right.

- Library code raises `LdoError` subclasses (`InputError`, `NotFoundError`,
  `AmbiguousError`, `ApiError`, ...) with a `hint` saying what to do, and never exits. Only
  the CLI turns errors into messages and exit codes (0 fine, 1 error, 2 usage, 3 needs
  attention, 130 interrupted).
- Data goes to stdout; notes, warnings and progress to stderr, through `cli/render.py`
  (`note`, `warn`, `error`, `emit`). In the `json` and `otlp` log formats those become log
  records, so never write to stderr directly.
- Every data command takes `-o table|json|csv|tsv` and `-p PROFILE`; lists of names take
  arguments, `-` for stdin and `-f FILE` with `--column`, `--sheet` and `--where`
  (`core.row_filters`). A list command also
  takes `sort: SortOption = None, unique: UniqueOption = None` before `output`, which
  `render.emit` applies to its rows; a command showing one record does not.
- Colour is decided once, in `core/colour.py` (the root's `--colour` flag, `NO_COLOR`,
  `FORCE_COLOR`, a terminal). Style with `colour.style`, or a `(text, colour)` table cell;
  sort and de-duplicate with `core/sorting.py`, never `sorted()` on display text.
- All HTTP goes through `core.http.ApiClient`, which applies `core/network.py` (the proxy
  and `no_proxy`) and `core/trust.py` (the public roots, the OS store and `ca_bundle`), and
  `az` runs with the same through `network.subprocess_env()`. Never call `requests` directly.
- Anything a person types that goes into a URL path or a query is validated first (names,
  ids, KQL values; a device name in KQL through `core.util.require_host`), with `re.fullmatch`: `^...$` with `match` lets a trailing line break
  through. A token or secret is never printed (only with an explicit `--raw`), never logged,
  and never accepted on the command line. A proxy address can hold a password: show one only
  through `network.redact` (a `Route`'s `shown`).
- Help text is rendered as markdown: no `<`, no `*`, and paragraphs reflow. A test checks.
- Do not hide findings from a scanner or linter by renaming things; fix the code, or say it
  is a false positive and why.
