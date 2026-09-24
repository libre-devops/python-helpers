# Changelog

All notable changes to libre-devops-helpers are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

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
