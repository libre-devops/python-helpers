# Libre DevOps Helpers

[![Lint and Test](https://github.com/libre-devops/python-helpers/actions/workflows/ci.yml/badge.svg)](https://github.com/libre-devops/python-helpers/actions/workflows/ci.yml)
[![CodeQL](https://github.com/libre-devops/python-helpers/actions/workflows/codeql.yml/badge.svg)](https://github.com/libre-devops/python-helpers/actions/workflows/codeql.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

`ldo`: importable Python helpers and a fast CLI for day-to-day DevOps and security work.
The Python sibling of the [LibreDevOpsHelpers](https://github.com/libre-devops/powershell-helpers)
PowerShell module.

It starts with Microsoft: Azure, Entra ID, Defender for Endpoint, Intune, Key Vault and Log
Analytics. The code is laid out by vendor, so more can join (HashiCorp and ServiceNow are
next) without disturbing what is there.

- check a list of devices across Entra, Defender and Intune in one fast pass, or watch them
  until every one is where it should be
- look up devices, users, groups, directory roles, sign-ins, app credentials and Conditional
  Access policies
- look up Defender machines, alerts, vulnerabilities and indicators, and run Advanced Hunting
- run Azure Resource Graph and Log Analytics queries, list a principal's role assignments,
  and read Defender for Cloud's secure score, recommendations and plans
- find secrets, certificates and keys (Key Vault) and app credentials (Entra) close to expiry
- see PIM eligibility, active and standing access, requests, approvals waiting on you, and
  what activating a role takes, across Azure resources, Entra roles and PIM for Groups
- switch the Azure CLI between named tenants and subscriptions, and check what a token holds

Everything is read-only apart from `az use`, which changes the Azure CLI's active account.
The whole project can be renamed for your organisation with one command; see
[Rebranding](#rebranding).

## Requirements

- Python 3.11 or later, and [uv](https://docs.astral.sh/uv/)
- The [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az`) on `PATH`,
  for Microsoft profiles that use it (the default)
- [just](https://just.systems/) is optional: `uv sync` installs it into the project
  environment (the `rust-just` package), so `uv run just ...` always works

## Install

```bash
uv tool install git+https://github.com/libre-devops/python-helpers
ldo welcome
ldo config init
```

Or from a clone, for development:

```bash
just sync            # or: uv sync
just install         # optional: puts ldo on PATH (uv tool, editable)
ldo config init
```

Run `ldo` on its own, or `ldo welcome`, for a greeting and the next step. The banner only
appears on a terminal, so scripts and CI never see it; set `LDO_NO_BANNER=1` to turn it off
there too, or `NO_COLOR=1` to keep it without colour.

## Configuration

`config init` writes `~/.config/ldo/config.toml` (override with `--config` or `LDO_CONFIG`;
on Windows it lives under `%APPDATA%`), with a `0600` mode on Linux and macOS. The file has a
section per vendor, and never holds a secret. Replace the placeholder ids:

```toml
# ca_bundle = "~/certs/proxy-ca.pem"      # optional: a custom CA for every HTTPS call

[microsoft]
default_profile = "prod-tenant"

[microsoft.profiles.prod-tenant]
description = "Production tenant"
tenant_id = "<tenant guid>"
workspace_id = "<Log Analytics workspace id>"   # optional: the default for 'logs query'

[microsoft.profiles.prod]
description = "Production subscription"
tenant_id = "<tenant guid>"
subscription_id = "<subscription guid>"
# mde_url = "https://api-eu.securitycenter.microsoft.com"   # optional regional endpoint

[microsoft.profiles.ci]
description = "Scheduled checks from GitHub Actions"
tenant_id = "<tenant guid>"
auth = "workload-identity"
client_id = "<app registration client id>"
```

A Microsoft profile is a tenant, optionally pinned to a subscription, in one cloud, with one
way of getting tokens. Unknown keys are rejected so typos fail loudly.

| Key | Meaning |
| --- | --- |
| `tenant_id` | Required. The tenant the profile acts in. |
| `subscription_id` | Pins the profile to one subscription; Azure commands then cover only it. |
| `cloud` | `public` (the default), `usgov` (GCC High) or `china`. Point the Azure CLI at the same cloud with `az cloud set`. |
| `auth` | How the profile gets tokens; see below. |
| `client_id` | The app registration, or user-assigned managed identity, to use. |
| `workspace_id` | The Log Analytics workspace `logs query` uses when `--workspace` is not given. |
| `mde_url` | A regional Defender for Endpoint endpoint. |

### Credentials

| `auth` | For | Needs |
| --- | --- | --- |
| `azure-cli` (default) | people at a terminal | `az login`; tokens are requested per tenant, so `az use` is optional |
| `interactive` | people who need scopes the Azure CLI lacks (PIM) | `client_id` of your own public client app; signs you in in a browser |
| `device-code` | the same, over SSH, in WSL, or anywhere without a browser | `client_id` of the same app; you enter a code at the device login page |
| `client-secret` | automation with a secret | `client_id`, and the secret in `AZURE_CLIENT_SECRET` |
| `workload-identity` | CI and Kubernetes, no secret at all | `client_id`, and a federated token from `AZURE_FEDERATED_TOKEN_FILE` or the GitHub Actions OIDC endpoint |
| `managed-identity` | code running on an Azure host | nothing, or `client_id` for a user-assigned identity |

`interactive` and `device-code` sign you in once per command. The refresh token that comes
with the first token gets tokens for other APIs without asking again, and every token is
kept in memory only: nothing is written to disk.

The environment variable names are the ones the Azure SDKs use, so a job configured for one
works for the other. In GitHub Actions, give the job `permissions: id-token: write` and add a
federated credential to the app registration whose subject matches the workflow:

```yaml
permissions:
  id-token: write
  contents: read

steps:
  - run: uv tool install git+https://github.com/libre-devops/python-helpers
  - run: ldo --config .github/ldo.toml entra app-credentials -p ci --expiring 30d
```

### Delegated sign-in (your own app registration)

The Azure CLI's token carries scopes Microsoft chose, and the PIM ones are not among them.
Register a public client app once per tenant and grant it the delegated read scopes, then
point a profile at it. An administrator grants consent once:

```bash
app=$(az ad app create --display-name "ldo (delegated sign-in)" \
  --public-client-redirect-uris http://localhost --is-fallback-public-client true \
  --query appId -o tsv)
graph=00000003-0000-0000-c000-000000000000       # Microsoft Graph
arm=797f4846-ba00-4fd7-ba43-dac1f8f63013         # Azure Service Management
for scope in Directory.Read.All RoleEligibilitySchedule.Read.Directory \
  RoleAssignmentSchedule.ReadWrite.Directory RoleManagementPolicy.Read.Directory \
  PrivilegedEligibilitySchedule.Read.AzureADGroup PrivilegedAssignmentSchedule.ReadWrite.AzureADGroup \
  RoleManagementPolicy.Read.AzureADGroup; do
  id=$(az ad sp show --id $graph --query "oauth2PermissionScopes[?value=='$scope'].id" -o tsv)
  az ad app permission add --id "$app" --api $graph --api-permissions "$id=Scope"
done
id=$(az ad sp show --id $arm --query "oauth2PermissionScopes[?value=='user_impersonation'].id" -o tsv)
az ad app permission add --id "$app" --api $arm --api-permissions "$id=Scope"
az ad app permission admin-consent --id "$app"
echo "client_id = \"$app\""
```

```toml
[microsoft.profiles.me]
tenant_id = "<tenant guid>"
auth = "interactive"            # or "device-code"
client_id = "<the app id printed above>"
```

Graph insists on a ReadWrite scope even to list PIM requests; `ldo` still only ever reads.

## Commands

```bash
ldo welcome                             # the banner, the config file, and what to run next
ldo profiles                            # every profile, which is active, and its sign-in
ldo az use test-tenant                  # switch az to a profile (signs in when needed)
ldo az whoami                           # az's active account and matching profile
ldo entra token graph -p prod-tenant    # get a token and check what it can do
pbpaste | ldo entra inspect-token --resource graph
```

### Devices across Entra, Defender and Intune

```bash
ldo devices check web01,web02,db01                       # in Entra and onboarded to Defender?
ldo devices check -f plan.csv --column FQDN --tag linux-servers --group "MDE Pilot Devices"
ldo devices watch -f hosts.txt --interval 5m --timeout 2h # poll until all complete
ldo devices watch web01 --max-passes 12 --active --compliant
ldo devices show web01.corp.example.com                  # one device, and what looks wrong
```

`check` is one fast pass: lookups for different devices run in parallel (`--workers`), and
each expected group's members are fetched once rather than once per device. `watch` repeats
the check every `--interval` until every device meets every expectation, stopping at
`--timeout` or `--max-passes` if you set them. Devices that already met everything are not
checked again unless you pass `--recheck`, so later passes stay cheap. Progress goes to stderr
after each pass, and the final table to stdout.

Expectations: `--entra/--no-entra` and `--defender/--no-defender` (both on by default),
`--active` (Defender health is Active), `--tag` and `--group` (repeatable), `--intune` and
`--compliant`.

`show` puts a device's Entra objects and groups, Defender record and (with `--intune`) Intune
record side by side, and flags what looks wrong: duplicate registrations, a disabled object,
Defender not onboarded, inactive or stale, and Defender or Intune pointing at a different
Entra device than the one found by name.

### Entra ID

```bash
ldo entra device-groups web01.corp.example.com
ldo entra group-devices "MDE Pilot Devices"
ldo entra group-members "Platform Admins" --kind user
ldo entra user-groups ana@example.com
ldo entra user-roles ana@example.com                  # active roles, and PIM-eligible ones
ldo entra sign-ins --user ana@example.com --since 7d --failures
ldo entra app-credentials --expiring 30d --service-principals
ldo entra ca-policies --state report-only
```

### Defender for Endpoint

```bash
ldo xdr machines web01 web02 --all-records
ldo xdr stale --older-than 30d
ldo xdr alerts --since 24h --severity medium
ldo xdr alerts --device web01 --include-resolved
ldo xdr vulns web01 --severity high
ldo xdr indicators
ldo xdr hunt --file queries/failed-logons.kql -o csv > failed-logons.csv
```

### Intune

```bash
ldo intune devices laptop-042 laptop-043
```

### Azure

```bash
ldo azure subscriptions
ldo azure resource-graph "resources | summarize count() by type | order by count_ desc"
ldo azure rbac ana@example.com                        # every role assignment that applies
ldo azure secure-score --controls
ldo azure recommendations --severity high
ldo azure defender-plans
```

Azure commands cover the profile's subscription when it pins one, otherwise every
subscription the credential can see in the tenant; `-s/--subscription` (repeatable) chooses.
`rbac` includes assignments made to the principal's groups and those inherited from
management groups.

### Privileged Identity Management

```bash
ldo pim eligible                       # roles you can activate, in all three areas
ldo pim active --permanent-only        # standing access: active roles with no end date
ldo pim requests --pending             # your requests still waiting
ldo pim approvals                      # requests waiting for you to approve
ldo pim eligible --azure --user ana@example.com
ldo pim settings "Global Administrator"                          # an Entra role
ldo pim settings Owner --scope /subscriptions/<id>               # an Azure role
ldo pim settings --group "Platform Admins" --owner               # a PIM for Groups group
```

Each command covers Azure resource roles (`--azure`), Entra roles (`--entra`) and PIM for
Groups (`--groups`), all three unless you pick. An area that cannot be read shows as a warning
with the reason (the tenant has no Entra ID P2, or the token lacks the scope) and the others
still show; the command fails only when every area does. Azure resource PIM works with the
Azure CLI's token; the Entra and group areas need a profile with delegated sign-in (above),
or, with `--user`, an app registration granted the application permissions. `settings`
shows the longest activation, whether MFA, a justification, a ticket or approval is needed,
and who approves. Nothing here activates or approves anything.

### Key Vault and Log Analytics

```bash
ldo keyvault expiry kv-app-prd kv-app-dev --within 60d
ldo keyvault expiry --all-vaults                      # every vault, found through Resource Graph
ldo logs query "Heartbeat | summarize arg_max(TimeGenerated, *) by Computer" --timespan 1d
```

`keyvault expiry` lists metadata only and never reads a secret value.

### Common options

- `-p/--profile` (or `LDO_PROFILE`) picks the profile. Without it, the vendor section's
  `default_profile` is used, then (for Microsoft) the Azure CLI's active account.
- `-o/--output` is `table` (the default), `json` (the services' full records, for `jq`) or
  `csv` (for spreadsheets). Data goes to stdout; notes, warnings and progress go to stderr.
- Commands that take names accept `"a,b,c"`, several arguments, `-` to read stdin, and
  `-f/--from-file`: one name per line (with `#` comments), or a CSV column named by
  `--column`.
- Queries (`xdr hunt`, `azure resource-graph`, `logs query`) come from the argument,
  `--file`, or stdin.
- `-v` / `-vv` turn on info or debug logging on stderr. `--log-format` (or `LDO_LOG_FORMAT`)
  picks `text`, `json` or `otlp`: one OTLP/JSON `ExportLogsServiceRequest` per line, which a
  collector's `otlpjsonfile` receiver reads as it is. `--log-level` (or `LDO_LOG_LEVEL`) sets
  the minimum level. Both variables mean the same as they do for `Write-LdoLog` in
  LibreDevOpsHelpers, so one pipeline setting controls both tools; the one difference is that
  with nothing set, `ldo` writes readable text.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Error, or a token check failed (`--strict` also fails on warnings) |
| 2 | Usage error |
| 3 | The command ran and found something that needs attention: a device missing or short of an expectation, a watch that hit its limit, or a credential, secret or certificate close to expiry |
| 130 | `devices watch` stopped with Ctrl-C |

Code 3 lets a scheduled job alert on findings while still failing loudly on errors.

## Permissions

Commands run with the permissions of the profile's credential. The Azure CLI's delegated
token is fixed by Microsoft and covers most of this tool, but not all of it:

| Commands | API | Needs | With the Azure CLI's token |
| --- | --- | --- | --- |
| `entra device-groups`, `group-devices`, `group-members`, `user-groups` | Graph | directory, device, group or user read | yes |
| `entra user-roles` | Graph | directory read; PIM eligibility needs `RoleEligibilitySchedule.Read.Directory` | active roles only |
| `entra sign-ins` | Graph | `AuditLog.Read.All` and directory read; Entra ID P1 | yes |
| `entra app-credentials` | Graph | `Application.Read.All` | yes |
| `entra ca-policies` | Graph | `Policy.Read.All` | no: Graph returns an empty list |
| `intune devices`, `--intune`, `--compliant` | Graph | `DeviceManagementManagedDevices.Read.All` | no |
| `xdr ...`, `--defender`, `--tag` | Defender | `Machine`, `Alert`, `Vulnerability`, `Ti` and `AdvancedQuery` read permissions, or a Defender role for delegated access | yes, through your Defender role |
| `azure ...` | ARM | Azure RBAC Reader | yes |
| `keyvault expiry` | Key Vault | Key Vault Reader (data plane), and a firewall that allows your address | yes |
| `logs query` | Log Analytics | Log Analytics Reader on the workspace | yes |
| `pim ... --azure` | ARM | Azure RBAC read at the scope; Entra ID P2 in the tenant | yes |
| `pim ... --entra` | Graph | `RoleEligibilitySchedule.Read.Directory`, `RoleAssignmentSchedule.ReadWrite.Directory` (Graph requires ReadWrite to list requests), `RoleManagementPolicy.Read.Directory` | no |
| `pim ... --groups` | Graph | `PrivilegedEligibilitySchedule.Read.AzureADGroup`, `PrivilegedAssignmentSchedule.ReadWrite.AzureADGroup`, `RoleManagementPolicy.Read.AzureADGroup` | no |

For the rows marked no, use a profile with its own app registration (`client-secret` or
`workload-identity`) granted the permission. `ldo entra token graph` shows which features a
token can serve, one line each.

### What the token checks mean

`entra token` and `entra inspect-token` decode the token and check expiry, not-before, that
the issuer matches the token's tenant, the audience against the API, and the tenant against
the profile. For each feature that uses the API, they report whether the token's scopes or
roles cover it (a warning, since delegated access can also come from the service's own RBAC).
The signature is **not** verified: this answers "is this the token I meant to get?", not "is
this token genuine?". The token value is never printed unless you pass `--raw`, and never
logged.

## Rebranding

To run this inside a company under the company's own name, rename it with one command.
Every name is a parameter:

```bash
just rebrand --command contoso --display-name "Contoso Helpers" --dry-run   # preview
just rebrand --command contoso --display-name "Contoso Helpers" \
  --package contoso_helpers --repository https://git.contoso.example/platform/contoso-helpers \
  --banner contoso-logo.txt                                                   # or --no-banner
```

| Parameter | Renames | Default when not given |
| --- | --- | --- |
| `--command` | the CLI command, and the config directory (`~/.config/<command>`) | unchanged |
| `--display-name` | the name in the banner, help and docs | unchanged |
| `--package` | the Python import name, in every import | unchanged |
| `--distribution` | the name you install | from `--package` |
| `--env-prefix` | every environment variable (`<PREFIX>_CONFIG`, `<PREFIX>_PROFILE`, ...) | from `--command` |
| `--error-class` | the base exception | from `--command`, e.g. `ContosoError` |
| `--repository` | every link to the repository | unchanged |
| `--banner` / `--no-banner` | the welcome art (plain ASCII) | unchanged |

The current names live in `brand.toml`, so the rename can be run again later, and the names
the running tool shows come from one module (`core/brand.py`). After rewriting, the recipe
refreshes the lock file and runs every check. `LICENSE` is never changed: the MIT licence
requires its copyright and permission notice to stay with the code. A test rebrands a copy of
the repository and runs the copy's whole test suite, so the rename keeps working as the code
grows.

## Using it as a library

The code is layered, and a test enforces the layering:

| Package | Depends on | What it holds |
| --- | --- | --- |
| `core` | nothing | vendor-neutral: errors, the config file, the brand, the token cache, HTTP client (retries, Retry-After, paging), command runner, polling, input parsing, query results, logging |
| `microsoft` | `core` | shared Microsoft layer: clouds, APIs as tokens see them, token checks, credentials, the Azure CLI runner, `[microsoft]` profiles |
| `microsoft.azcli` | `core`, `microsoft` | Azure CLI accounts, sign-in and profile switching |
| `microsoft.entra` | `core`, `microsoft` | devices, users, groups, roles, sign-ins, app credentials, Conditional Access |
| `microsoft.xdr` | `core`, `microsoft` | Defender machines, alerts, vulnerabilities, indicators, Advanced Hunting |
| `microsoft.intune` | `core`, `microsoft` | managed devices and compliance |
| `microsoft.azure` | `core`, `microsoft` | subscriptions, Resource Graph, RBAC, Defender for Cloud |
| `microsoft.keyvault` | `core`, `microsoft` | secret, certificate and key metadata |
| `microsoft.loganalytics` | `core`, `microsoft` | KQL queries against a workspace |
| `microsoft.pim` | `core`, `microsoft` | PIM eligibility, assignments, requests, approvals and settings, for Azure resources, Entra roles and groups |
| `microsoft.devices` | the above, plus `entra`, `xdr`, `intune` | device checks, watches and the combined view |
| `cli` | all of the above | the `ldo` command, a thin layer that parses, calls and renders |

Every client takes any token provider, so where tokens come from is the caller's choice.

```python
from libre_devops_helpers.core import CachingTokenProvider, PollLimits
from libre_devops_helpers.microsoft import credential_for, load_config
from libre_devops_helpers.microsoft.devices import DeviceChecker, Expectations, watch
from libre_devops_helpers.microsoft.entra import EntraClient
from libre_devops_helpers.microsoft.xdr import XdrClient

profile = load_config().get("prod-tenant")
tokens = CachingTokenProvider(credential_for(profile))

with EntraClient.for_profile(profile, tokens) as entra, XdrClient.for_profile(profile, tokens) as xdr:
    checker = DeviceChecker(entra=entra, xdr=xdr)
    expectations = Expectations(tags=("linux-servers",))
    run = checker.check(["web01", "web02"], expectations)
    outcome = watch(checker, ["web01", "web02"], expectations, PollLimits(interval=300, timeout=7200))
    print(outcome.reason, outcome.passes)
```

Library code raises `LdoError` subclasses and never exits; only the CLI turns errors into
messages and exit codes.

## CI/CD

Every pull request and push to `main` runs `.github/workflows/ci.yml`:

| Job | What it does |
| --- | --- |
| Secret scan | gitleaks over every commit, with the checksum-pinned release; `.gitleaks.toml` allows only the public Microsoft endpoints and application ids the code holds |
| Lint | `ruff check` and `ruff format --check`, after `uv sync --locked` |
| Dependency audit | `pip-audit` over the locked, hashed dependency tree |
| Test | pytest on Python 3.11 to 3.14 on Linux, and 3.13 on Windows and macOS, including the rebrand test |
| Build | builds the sdist and wheel once, installs the wheel in a clean environment, and keeps both as the run's artifact |

CodeQL scans the Python code and the workflows on every change and weekly; Dependency
Review comments on pull requests that change dependencies; Dependabot proposes updates to
the uv lock file and to the actions weekly. Third-party actions are pinned to a commit.

To release, set the version in `pyproject.toml` and `src/libre_devops_helpers/__init__.py`
(a test keeps them equal), merge, and push a tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

`.github/workflows/release.yml` runs the same CI as a gate, checks the tag matches the
version, and publishes the files that gate built (not a rebuild) as a GitHub release with
`SHA256SUMS`.

## Development

```bash
just check           # ruff lint + format check + pytest: what a change must pass
just test -k devices # extra args go to pytest
just test-311        # the suite on the oldest supported Python
just fmt             # apply formatting and safe lint fixes
just run welcome     # run the CLI from the working tree
```

Tests never touch the network, a real `az`, or a real clock: HTTP goes through a fake
`requests` adapter, `az` through a fake subprocess runner, and polling through a fake clock,
so an hour-long watch runs in microseconds. Runtime dependencies are kept to `requests` and
`typer`; everything else, the credentials included, is the standard library.

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request, and
[SECURITY.md](SECURITY.md) to report a vulnerability.

## Licence

[MIT](LICENSE)
