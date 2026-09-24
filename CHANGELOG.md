# Changelog

All notable changes to libre-devops-helpers are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## Unreleased

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
