# Changelog

All notable changes to libre-devops-helpers are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- `ldo xdr timeline DEVICE`: a device's events, newest first, as the portal's timeline shows
  them: processes, network connections, files, registry, logons, image loads, other device
  events and alerts, with `--type` to choose, a window (`--since`, `--today`, `--from` and
  `--to`) and `--limit`. Defender has no API for the timeline itself, so this is one Advanced
  Hunting query over the device tables, through Graph or `--endpoint`; the docs say what
  that means (30 days, a row limit, the events without the portal's extras).
- `ldo xdr detections list`, `show` and `export`: Defender XDR's custom detection rules, the
  detections Sentinel runs from the Defender portal, read through Graph. `list` exits 3 when
  Defender has turned a rule off itself (`autoDisabled`), the one sign of failing runs left
  once the legacy `lastRunDetails` goes on 2026-10-01. `export` (and `show --yaml`) writes
  each rule as a YAML file for terraform-msgraph-xdr-custom-detection-rules, in its folder
  layout, checked against its schema, with `TODO(export)` comments for what needs review.
- `ldo logs ingestion`: which tables a workspace is receiving, from its `Usage` table: when
  each last got data, for how long it has been quiet, and its GB and billable GB. Quiet
  tables come first, and it exits 3 when there are any.
- `--from` and `--to` take a time as well as a day: `--from 2026-09-24T09:00 --to
  2026-09-24T12:30`, local time, or UTC with a `Z`. For `xdr incidents` as well.
- `-o tsv` on every data command: tab-separated values, one row a line, with no header, as
  the Azure CLI's `-o tsv`, for shell pipelines. A tab or line break inside a value becomes a
  space.
- `--colour` and `--no-colour` (or `--color`, `--no-color`) before any command: colour, or
  none, whatever the output is, e.g. for `less -R`. `FORCE_COLOR` turns colour on too.
- `--sort COLUMN[:desc]` and `--unique COLUMN` on every list, by the column names the table
  shows: `ldo xdr vulns web01 --sort severity:desc --sort cvss:desc`, or
  `ldo xdr machines -f hosts.txt --sort "last seen:desc" --unique device`. Numbers, versions,
  severities and dates sort as such, names naturally (`web2` before `web10`), blanks last.
  For the table, CSV and TSV; JSON is left for `jq`.
- `core.sorting` (`sort_records`, `unique`, `natural_key`) and `core.colour` (the colour
  decision, ANSI styles, coloured JSON), for library use as well as the CLI.
- For library use: `GraphServiceClient` and `ArmServiceClient` (`microsoft.api_clients`)
  and `core.http.ServiceClient`, which every client now builds on, so each has `create`,
  `for_profile` and `with` alike (ServiceNow's `TableClient` gains `with`); `core.fields`
  for reading API JSON; `core.util.require_guid`. `ApiClient(network_settings=...)` gives one
  client its own proxy and certificates; `EntraClient.look_up_devices` looks names up and checks group membership in
  one call; `core.probe` holds the network test's probe; `core.auth.Pkce` the proof key a
  browser sign-in uses.

### Security

- `ldo network test` printed a proxy address's password (`http://user:password@proxy`, as
  `HTTPS_PROXY` often holds) in its table, its JSON and its hints. Proxy addresses are now
  shown as `user:***@` everywhere; the real one is still what calls go through.

### Fixed

- Two commands signing in at once (two terminals, say) could lose one's kept sign-in, or
  fail on a shared temporary file. The token cache is now changed under a lock file.
- Names and ids checked before they go into a URL (machine ids, job and stream ids, vault
  and Logic App names, profile names) let a trailing line break through. They no longer do.
- `entra devices` lists a name's devices most recently signed in first, so the ones marked
  as older records are older.
- `network test` reads a TLS-inspecting proxy's certificate through a proxy that wants a
  user and password, as the calls themselves do.

### Changed

- `pim settings -o json` writes snake_case keys with real values (`"requires_mfa": true`,
  `"max_activation": "PT8H"`), as every other command's JSON does. It wrote the table's
  labels (`"Needs MFA": "yes"`). Every command's JSON shape is now held by a test.
- Something given that cannot be used (a malformed id, an empty query, an unknown
  severity or resource) is an `InputError` everywhere, for library callers catching it; a
  profile that cannot do what was asked is a `ConfigError`.
- On a terminal, a table's last column is cut to fit the window, with an ellipsis, so a long
  message (an error's detail, say) no longer wraps across the table. Piped, redirected,
  CSV, TSV and JSON output keep every character.
- `self-test`'s progress lines line up, whatever the count.
- The code is checked harder: mypy in strict mode, ruff's security rules, a complexity limit
  of 10 per function (the device checker, the token checks and several commands are split
  into named steps), and a docstring on every public module, class and function. The API
  clients share their setup, models read API JSON one way, and the devices, entra, logicapp
  and xdr commands are split into a module per area. None of it changes what a command
  does, and a test now proves that for every command's JSON.

## 0.5.1rc1

### Added

- `ldo self-test` (hidden from `--help`): runs every read-only command against a device,
  user and group you name, discards their output, and reports each as ok, attention,
  refused, usage or CRASH, a crash with the lines of `ldo` it came through. `--report`
  writes it all to a file. For trying a build in a real tenant before a release.

### Fixed

- `xdr vulns` (and anything showing a date) crashed with `OverflowError` on Defender's
  "not known" date, `0001-01-01`. Such dates now show as `-`, and a date the platform cannot
  convert to local time is shown in UTC rather than failing.
- A short name found nothing when Defender (or Entra) knows the device by its FQDN. It is
  now looked for as the first label of one: `web01` finds `web01.corp.example`, never
  `web010.corp.example`. `xdr machines` marks such a match `prefix`.

## 0.5.0

### Added

- Corporate proxy support. Every HTTPS call, and every `az` `ldo` runs, follow one set of
  rules: loopback and the metadata endpoint always direct, then `no_proxy` and `NO_PROXY`,
  then `LDO_PROXY_ADDRESS`, the config file's `proxy`, `HTTPS_PROXY` / `HTTP_PROXY` /
  `ALL_PROXY`, and the operating system's setting. An address without a scheme means
  `http://`, as for cntlm and Px, which sign in to an NTLM or Kerberos proxy for you.
- The operating system's certificate store is trusted by default, with the public roots
  and the config file's `ca_bundle`, in one bundle the Azure CLI is handed as
  `REQUESTS_CA_BUNDLE` too, so both work behind a TLS-inspecting proxy whose root IT has
  installed. `LDO_CA_BUNDLE`, `REQUESTS_CA_BUNDLE` or `CURL_CA_BUNDLE` names a bundle to use
  exactly instead. No new dependency.
- `ldo network test`: asks Entra ID, Graph, Azure Resource Manager, Defender and each
  ServiceNow instance (and any `--url`) for an unsigned answer, and says which proxy each
  call used, which certificates are trusted, and what to try when one fails: a proxy's
  NTLM sign-in (cntlm or Px), a proxy that is not running, a TLS-inspecting proxy's
  certificate (with its issuer named), or a local proxy listening on 3128 or 3129.
- `AI.md`: instructions for AI coding assistants, read by Claude Code (through `CLAUDE.md`),
  GitHub Copilot (`.github/copilot-instructions.md`, and `AGENTS.md` for its coding agent)
  and Codex (`AGENTS.md`). `AGENTS.md` is written from it by `just ai`, and a test fails
  when it falls behind.

### Changed

- The README installs from PyPI (`uv tool install`, `pipx`, `uv pip` or `pip`), with a
  PyPI badge; installing a tag from GitHub is still shown.

### Fixed

- `ca_bundle` replaced the public roots rather than adding to them, so a host a proxy does
  not inspect (sign-in often is not) failed to verify, and it never reached the Azure CLI.
  It now adds to the public roots and the OS store, for both.


## 0.4.1

### Added

- Releases can publish to PyPI through trusted publishing, once the repository variable
  `PUBLISH_PYPI` is `true`: the same wheel and sdist, last, after the images and the GitHub
  release. The README PyPI shows has its relative links pointed at GitHub.

### Changed

- The package metadata links to the docs and the changelog, and its keywords name
  Graph, Sentinel, PIM, Logic Apps and ServiceNow.

## 0.4.0

### Added

- `ldo entra devices`: look devices up in Entra ID by name (arguments, stdin, or `-f` with
  a file or workbook column), and with `--group` check each is in an Entra group, named by
  its object id or display name. Each group's members are fetched once; nested membership
  counts unless `--direct`. Exits 3 when a device is missing, or not in every group.
- Defender device groups: `xdr machines` shows each machine's device group, and
  `devices check` and `watch` take `--device-group NAME` as an expectation.
- `ldo azure automation`: `accounts`, `jobs` (a runbook's recent runs, with `--runbook`,
  `--status`, `--failed` and `--since`), `logs` (a job's output, warning, error and other
  streams, oldest first, with why it failed; the newest job by default) and `output` (the
  job's output as text, for piping). An account is named by name or resource id. `jobs`
  and `logs` exit 3 on a failed job.

- `-o json` is coloured on a terminal (keys, strings, numbers, booleans, and brackets in
  the banner's rainbow by depth); piped, it stays plain JSON.
- `ldo json`: pretty-print JSON from stdin or a file, one document or JSON Lines, in
  colour on a terminal, with `--sort-keys`, `--compact`, `--indent` and `--colour`.
  `--yaml` writes YAML instead, with the standard library alone: strings a YAML reader
  could misread are quoted, and multi-line strings become `|` blocks.

- OTLP logs take the same variables as `Write-LdoLog`: `LDO_SERVICE_NAME`,
  `LDO_SERVICE_VERSION` and `LDO_DEPLOYMENT_ENVIRONMENT` for the resource, and
  `LDO_TRACE_ID`, `LDO_SPAN_ID` and `LDO_CORRELATION_ID` to put every record in a trace
  (an id that is not valid hex is left out). `OTEL_SERVICE_NAME` and
  `OTEL_RESOURCE_ATTRIBUTES` are read too.

### Changed

- With `--log-format otlp` or `json`, stderr holds only log records: the notes, warnings
  and errors `ldo` prints become records (an error's hint an attribute), so the stream is
  clean JSON Lines for a collector. Tested against OpenTelemetry Collector 0.161 through
  the `otlp_json_file` receiver, and `file_log` with the `otlp_json` connector.
- OTLP records use the semantic conventions' current attribute names,
  `code.function.name` (fully qualified) and `code.line.number`, in place of the
  deprecated `code.function` and `code.lineno`.

### Fixed

- Help text keeps its paragraphs together rather than breaking where the source lines
  did, and a test keeps help text free of what markdown would swallow.

## 0.3.0

### Changed

- The README is a short front page: what `ldo` does, a table of every command group, install,
  a quickstart and links. The detail moved to `docs/`, one page per area, with its prose cut
  down, and `ldo --help` links there.
- Hints that said "see the README" link to the page they mean.
- The justfile groups its recipes, drops the ones that only wrapped `just run` (`use`,
  `token`, `config-init`, `check-devices`, `watch-devices`), and adds `audit`, `secrets`,
  `build`, `lock`, `ci` (everything CI checks) and `release` (checks, then tags and pushes).
- The descriptions in `ldo --help`, the package metadata and the image labels name what the
  tool now covers.

### Added

- A test runs every `ldo` example in the README and docs with `--help`, checks every `just`
  example is a recipe, follows every link and anchor, and keeps the pinned install version
  in step with the release.

## 0.2.1

### Fixed

- The 0.2.0 release stopped before publishing the default image and the GitHub release:
  its arm64 build compiled the Azure CLI's 12,000 files under emulation and ran out of
  time. The Azure CLI's bytecode is now compiled on the build machine's own platform (it
  is the same on every architecture), in seconds. Only `0.2.0-slim` was published.
- Every push and pull request now builds both architectures, so a build that fails only
  under emulation is caught before a release.

### Security

- The default image's Azure CLI now runs cryptography 50.0.1 (CVE-2026-69247,
  CVE-2026-69248 and CVE-2026-69249). Azure CLI 2.90.0 pins msal 1.36.0, which caps
  cryptography below 49, so msal 1.39.0 is forced as well until Microsoft moves the pin.
- `config init` creates the config file readable only by you, rather than narrowing it
  after writing.

### Changed

- The container scan reports findings that have a fix to the Security tab. The full list,
  unfixed Debian findings included, is kept with each run as the `trivy-<variant>`
  artifact.
- Code scanning findings in the tests and scripts are fixed: URL checks compare the host,
  calls with side effects are made before they are asserted, protocol methods have
  docstrings rather than empty bodies, and the ServiceNow runtime no longer imports the
  runtime that imports it.

## 0.2.0

### Added

- Names from Excel workbooks: `-f` reads `.xlsx`, `.xlsm`, `.xltx` and `.xltm` as well as
  text and CSV, for example `ldo devices check -f plan.xlsx --column FQDN`. `--sheet` picks
  the tab; without it, the one visible sheet with the column is used. A header may sit
  below title rows, in CSV files too. Hidden and filtered rows are read, with a warning.
  The reader is the standard library alone: values as Excel saved them, no formulas
  recalculated, no macros run, and each part size-capped with document type declarations
  refused. Legacy `.xls`, `.xlsb`, `.ods` and password-protected files get a hint to save
  as `.xlsx` or `.csv`.
- Container images on GitHub Container Registry, for `linux/amd64` and `linux/arm64`: the
  tool with the Azure CLI (`latest`), for signing in as yourself, and the tool alone
  (`slim`), on a digest-pinned `python:3.14-slim` base, as an unprivileged user. Floating, exact and immutable stamped
  tags, with build provenance and SBOM attestations.
- A patching pipeline for the images: every build is smoke tested and scanned with Trivy
  (fixed high or critical findings fail the `slim` image; fixed critical ones fail the
  default image), a weekly run rebuilds the latest release with the newest Debian security updates
  and republishes only when a package changed, and Dependabot keeps the base images and the
  Azure CLI's lock file current.
- `just image`, `image-slim`, `image-run` and `image-scan`, and `just coverage`.
- Line and branch coverage in CI, failing below a floor set in `pyproject.toml`.
  The README's coverage badge comes from CI too: `badges.yml` publishes the total to a
  `badges` branch after each passing run on main, with no third-party service.
- Signing in again when a sign-in lapses. When the Azure CLI's refresh token has run out
  (a sign-in frequency policy, 90 days unused, a password change, a revoked session, new
  MFA), the error now names the cause (`ReauthRequired`, with the Entra ID code
  explained), and on a terminal the tool offers to sign the Azure CLI back in to that
  tenant, then carries on and restores the active account. `devices check` and `watch`
  ask on the main thread and repeat a pass a lapse interrupted. `LDO_REAUTH=device-code`
  or `off` changes or stops the question; scripts and CI never see it.
- An `interactive` or `device-code` profile now keeps its refresh token between
  commands, so you are not asked to sign in for each one. `token_cache` picks where:
  `file` (the default: plaintext, 0600, refused if other accounts can read it, and it
  works headless), `keychain` (macOS Keychain or the Linux Secret Service through the new
  optional `keychain` extra, and DPAPI on Windows) or `memory` (nowhere, as before).
  `ldo entra sign-out` forgets it. Access tokens are never kept.
- `ldo graph`: a fast way to read Microsoft Graph with a profile's sign-in. `whoami` (who
  the token is for, its scopes or roles, its expiry), `token` (as `entra token graph`),
  `get` for any path or pasted Graph URL (paging with `--all` and `--limit`, `--select`,
  `--filter`, `--search`, `--count`, `--orderby`, `--expand`, `--top`, `--beta`, and
  `ConsistencyLevel` when an advanced query needs it), `get-user`, `get-device`,
  `get-group`, `get-app` and `get-sp` by name or id, and `hunt`. Read-only throughout.
- `ldo devices av-signature` (and `ldo device av-signature`): the Defender Antivirus
  signature, engine and platform versions of devices, their antivirus mode and Defender's
  definitions check, from a built-in hunting query, through Graph or with `--endpoint`.
  Names come as for `devices check`, `-f` workbooks included. `--at-least` flags older
  signatures, `--show-query` prints the KQL, and it exits 3 for a device not found, out
  of date or behind.
- `ldo xdr hunt` now runs through Graph's `runHuntingQuery`, covering every Defender XDR
  table (email, identity, cloud apps and alerts as well as devices), with `--timespan`;
  `--endpoint` keeps the Defender for Endpoint API, which the Azure CLI's sign-in can use.
- `ldo logicapp`, ported from the LibreDevOpsHelpers LogicApps module, for Consumption
  Logic App workflows (Sentinel playbooks among them): `check` (the offline contract checks,
  a gate with `--strict`), `params`, `references` (connection keys used and whether wired),
  `connections`, `order` (deploy tiers from dispatch actions), `diff` (across shapes),
  `defaults` and `rewrite` (lifting between estates), `export` (deployed workflows to
  files) and `validate` (the resource provider's verdict, deploying nothing). Templates
  with unrendered Terraform tokens are read as they are.
- `ldo xdr incidents top`, `latest`, `list`, `summary` and `show`: Defender XDR's incident
  queue through the Graph security API, Sentinel's incidents included in the unified
  platform. Built-in windows (`--today`, `--yesterday`, `--since`, and `--from`/`--to` for
  between days, taken whole in local time, or `--updated` for last updates), with
  `--status`, `--severity`, `--source sentinel` (and the other Defender services) and
  `-n`. `show` gives the alerts, devices, users and the portal link. Needs
  `SecurityIncident.Read.All`, which `entra token` now checks for.
- ServiceNow: `ldo snow sign-in`, `sign-out`, `whoami`, `token`, `instance` and `apps`,
  and a `[servicenow]` config section (or just `SNOW_INSTANCE_URL` and friends). Sign-in
  is OAuth through an application registry entry: in a browser, pasting back where it
  lands (single sign-on, MFA and headless machines included), or with a password once;
  the refresh token, and a client secret typed in at sign-in, are kept in the private
  file. `auth = "basic"` remains for instances that allow it, and a 401 explains
  ServiceNow's new block on basic sign-in for interactive accounts.
- An `interactive` profile signs in with a device code when no browser can be opened
  (a headless machine), as the Azure CLI does.
- A 401 is retried once with a new token, and a claims challenge (continuous access
  evaluation) gets a hint to sign in again. `interactive` and `device-code` profiles say
  why they are signing in again.

### Changed

- The tests now mirror the package (`tests/core`, `tests/microsoft/<feature>`, `tests/cli`,
  `tests/cli/commands`), with the shared fakes split into a `fakes` package, one module per
  concern; a test keeps the two trees in step. Many more CLI paths are tested.
- A release now publishes the container images before the GitHub release, so a release
  never exists without them.
- The README opens with the Libre DevOps logo and centred badges, as the organisation's
  profile does, with a rule between sections.

### Fixed

- `just use` and `just token` ran commands that had moved under `az` and `entra`.
- Four CLI tests failed in GitHub Actions, where Typer styles and wraps usage errors; they
  now compare the message's plain text.
- A sheet test's 70,000 character id failed on Windows, which caps an environment
  variable (pytest's `PYTEST_CURRENT_TEST`) at 32,767 characters; its cases have short ids.

### Security

- CI's dependency audit now covers the optional extras too.

## 0.1.0

First public release.

### Added

- `ldo` command line tool, installed as a console script, with command groups for `az`,
  `entra`, `xdr`, `intune`, `azure`, `keyvault`, `logs` and `devices`.
- A config file at `~/.config/ldo/config.toml` with a section per vendor. Microsoft
  profiles live under `[microsoft.profiles.<name>]`: named tenants, optionally pinned to a
  subscription, in the `public`, `usgov` or `china` cloud. `config init` writes a template
  and `config path` shows where it is.
- Credentials: the Azure CLI (the default), client secret, workload identity (a federated
  token file, or GitHub Actions OIDC) and managed identity (App Service and IMDS). Secrets
  come from the environment, never the config file.
- `profiles` to list every profile; `az use` and `az whoami` to switch the Azure CLI
  between profiles and show the active account.
- `entra token` and `entra inspect-token` to get or decode an access token and check its
  expiry, issuer, audience and tenant, and which features its scopes or roles cover.
- `devices check`, a fast parallel check of many devices against expectations (in Entra,
  onboarded and active in Defender, tagged, in groups, enrolled and compliant in Intune);
  `devices watch`, which repeats it until complete within an interval, timeout and pass
  limit you set; and `devices show`, one device across services with what looks wrong.
- `entra device-groups`, `group-devices`, `group-members`, `user-groups`, `user-roles`
  (active and PIM-eligible), `sign-ins`, `app-credentials` and `ca-policies`.
- `xdr machines`, `stale`, `alerts`, `vulns`, `indicators` and `hunt` (Advanced Hunting).
- `intune devices`.
- `azure subscriptions`, `resource-graph`, `rbac`, `secure-score`, `recommendations` and
  `defender-plans`.
- `keyvault expiry`, reading metadata only, for named vaults or every vault found through
  Resource Graph.
- `logs query` for Log Analytics and Sentinel workspaces.
- `pim eligible`, `active` (with `--permanent-only` for standing access), `requests`,
  `approvals` and `settings`, across Azure resource roles, Entra roles and PIM for Groups,
  for the signed-in user or a named one. An area that cannot be read is a warning, not a
  failure. Everything reads; nothing activates or approves.
- `interactive` (browser, with PKCE) and `device-code` sign-in for your own public client
  app registration, for delegated scopes the Azure CLI's token lacks. Tokens and refresh
  tokens stay in memory for the one command.
- `-o table|json|csv` on every data command; names from arguments, stdin, text files or a
  CSV column; `--log-format text|json|otlp` and `--log-level`, which read the same
  `LDO_LOG_FORMAT` and `LDO_LOG_LEVEL` variables as LibreDevOpsHelpers.
- Exit code 3 when a command ran and found something that needs attention, so scheduled
  jobs can alert on findings.
- `welcome`, and a Libre DevOps unicorn banner (traced from the logo, coloured in diagonal
  bands) on bare `ldo` and `config init`, shown only on a terminal.
- `just rebrand`, which renames the command, package, distribution, environment variable
  prefix, error class, repository links and banner for use under another organisation's
  name, with every name a parameter.
- CI that scans every commit for secrets (gitleaks), audits the locked dependencies
  (pip-audit), tests on Python 3.11 to 3.14 and on Windows and macOS, and builds once; and a
  release workflow that publishes that build as a GitHub release when a version tag is
  pushed.
- Importable packages laid out by vendor (`core`, then `microsoft` and its features), with
  the layering between them enforced by a test.
