<div align="center">

<a href="https://libredevops.org">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://libredevops.org/assets/libre-devops-white.png">
    <img alt="Libre DevOps" src="https://libredevops.org/assets/libre-devops-black.png" width="320">
  </picture>
</a>

# Libre DevOps Helpers

`ldo`: importable Python helpers and a fast CLI for day-to-day DevOps and security work.

[![Lint and Test](https://github.com/libre-devops/python-helpers/actions/workflows/ci.yml/badge.svg)](https://github.com/libre-devops/python-helpers/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/libre-devops/python-helpers/badges/coverage.json)](https://github.com/libre-devops/python-helpers/actions/workflows/ci.yml)
[![CodeQL](https://github.com/libre-devops/python-helpers/actions/workflows/codeql.yml/badge.svg)](https://github.com/libre-devops/python-helpers/actions/workflows/codeql.yml)
[![Container](https://github.com/libre-devops/python-helpers/actions/workflows/container.yml/badge.svg)](https://github.com/libre-devops/python-helpers/actions/workflows/container.yml)

[![Release](https://img.shields.io/github/v/release/libre-devops/python-helpers?label=release&color=1793D1)](https://github.com/libre-devops/python-helpers/releases)
[![Container images](https://img.shields.io/badge/ghcr.io-python--helpers-2496ED?logo=docker&logoColor=white)](https://github.com/libre-devops/python-helpers/pkgs/container/python-helpers)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

</div>

---

The Python sibling of the [LibreDevOpsHelpers](https://github.com/libre-devops/powershell-helpers)
PowerShell module.

It covers Microsoft (Azure, Entra ID, Defender for Endpoint, Intune, Key Vault and Log
Analytics) and, newly, ServiceNow: sign-in, the instance, and its applications, with
Security Incident Response next. The code is laid out by vendor, so more can join (HashiCorp is
next) without disturbing what is there.

- check a list of devices across Entra, Defender and Intune in one fast pass, or watch them
  until every one is where it should be
- look up devices, users, groups, directory roles, sign-ins, app credentials and Conditional
  Access policies
- look up Defender machines, alerts, vulnerabilities and indicators, and run Advanced Hunting
  over the whole Defender XDR schema
- read anything in Microsoft Graph quickly: `ldo graph get users`, `get-device web01`,
  `whoami`, and a Graph token when a script needs one
- run Azure Resource Graph and Log Analytics queries, list a principal's role assignments,
  and read Defender for Cloud's secure score, recommendations and plans
- find secrets, certificates and keys (Key Vault) and app credentials (Entra) close to expiry
- see PIM eligibility, active and standing access, requests, approvals waiting on you, and
  what activating a role takes, across Azure resources, Entra roles and PIM for Groups
- switch the Azure CLI between named tenants and subscriptions, and check what a token holds
- take its lists of names however they come: arguments, stdin, a text file, a CSV, or a
  column of an Excel workbook, title rows and all
- run from a container image, with or without the Azure CLI inside, patched weekly

It works as you: it signs in with your own account (through the Azure CLI by default) and
can read only what you can. Everything is read-only apart from `az use`, which changes the
Azure CLI's active account.
The whole project can be renamed for your organisation with one command; see
[Rebranding](#rebranding).

---

## Requirements

- Python 3.11 or later, and [uv](https://docs.astral.sh/uv/)
- The [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az`) on `PATH`,
  for Microsoft profiles that use it (the default), or the [container image](#container-images),
  which has it inside
- [just](https://just.systems/) is optional: `uv sync` installs it into the project
  environment (the `rust-just` package), so `uv run just ...` always works

---

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

Or run it from the [container image](#container-images), with nothing to install but podman
or docker.

Run `ldo` on its own, or `ldo welcome`, for a greeting and the next step. The banner only
appears on a terminal, so scripts and CI never see it; set `LDO_NO_BANNER=1` to turn it off
there too, or `NO_COLOR=1` to keep it without colour.

---

## Container images

Each release is published to GitHub Container Registry in two variants, for `linux/amd64`
and `linux/arm64`:

| Image | What is inside | For |
| --- | --- | --- |
| `ghcr.io/libre-devops/python-helpers:latest` | the tool and the Azure CLI | signing in as yourself: the default `azure-cli` profiles, and `ldo az` |
| `ghcr.io/libre-devops/python-helpers:slim` | the tool alone | `device-code` profiles, and automation |

Both are built on the official `python:3.14-slim` (Debian 13) image, pinned by digest, and
run as an unprivileged user (uid 10001) with `/work` as the working directory. The Azure
CLI (about 700 MB of the default image) lives in a virtual environment of its own, locked with hashes in
`container/azure-cli`, so its many pinned dependencies never meet the tool's. It has no pip,
so `az extension add` does not work there; the tool needs no extensions.

Tags, for `slim` with a `-slim` suffix:

| Tag | Moves? | Meaning |
| --- | --- | --- |
| `0.2.1` | yes, to patched rebuilds | that release |
| `0.2` | yes | the newest 0.2.x (from 1.0, `1` too) |
| `latest` / `slim` | yes | the newest release |
| `0.2.1-20260928.57` | never | one build: the date and workflow run |

Pin by digest (`ghcr.io/libre-devops/python-helpers@sha256:...`) or by a stamped tag where
you need a build that never changes, and by `0.2` where you want patches as they land. Each
pushed image carries a build provenance attestation and an SBOM, which you can check with
`gh attestation verify oci://ghcr.io/libre-devops/python-helpers:0.2 --owner libre-devops`.

### Running it

The image signs in as you, through the Azure CLI inside it. Give the Azure CLI's state
(`~/.azure`) a named volume, so you sign in once and later containers reuse it, without
sharing your own `~/.azure` with the image. With rootless podman, map your user to the
image's so it can read your config and the directory holding your plan:

```bash
podman volume create ldo-azure
alias ldo='podman run --rm -it --userns=keep-id:uid=10001,gid=10001 \
  -v ldo-azure:/home/ldo/.azure \
  -v ~/.config/ldo:/home/ldo/.config/ldo:ro,z \
  -v "$PWD":/work:ro,z \
  ghcr.io/libre-devops/python-helpers:latest'

ldo az use prod-tenant --device-code      # sign the Azure CLI in, once
ldo devices check -f plan.xlsx --column FQDN --tag linux-servers
```

There is no browser inside a container, so sign in with a device code. When the sign-in
lapses, the tool offers to sign you in again, as it does outside a container. With docker,
use `--user "$(id -u):$(id -g)"` in place of `--userns`. The `z` option relabels the
mounts for SELinux (Fedora, RHEL) and does nothing elsewhere.

`slim` has no Azure CLI. Use it with a `device-code` profile (add `token_cache = "file"`
and a volume at `/home/ldo/.local/state/ldo` to keep the sign-in between runs), or for
automation: mount a config whose profile has `auth = "workload-identity"` and pass the
job's federated token settings through (`-e AZURE_FEDERATED_TOKEN_FILE` and a mount for
the file, or `-e ACTIONS_ID_TOKEN_REQUEST_URL -e ACTIONS_ID_TOKEN_REQUEST_TOKEN` on GitHub
Actions).

### Building it

```bash
just image                 # the default image (with the Azure CLI), tagged localhost/ldo:dev
just image-slim            # the tool alone, tagged localhost/ldo:dev-slim
just image-run az whoami   # run it: this directory at /work, your config, the ldo-azure volume
just image-scan slim       # the vulnerability scan CI runs (needs trivy)
```

`podman build .` and `docker build -f Containerfile .` work as well.

### Why the Azure CLI is not a Python dependency

It could be (it is on PyPI), but it would make the tool much heavier and harder to use as a
library. `azure-cli` pulls in about 150 packages and 350 MB, and pins many of them exactly,
so any project that imports this package would inherit those pins and their conflicts.
The tool does not need the Azure SDKs either (`azure-identity`, `azure-mgmt-*`): it calls
the REST APIs with `requests`, and its own credentials cover client secrets, workload
identity, managed identity, and browser or device code sign-in without `az`. The Azure CLI
is only there for the default sign-in, which reuses the session you already have, so it
stays an outside program: on your `PATH`, or inside the default image.

---

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

The tool is for people, working as themselves: everything it reads, it reads with your
own account and your own permissions. There are three ways to sign in as yourself:

| `auth` | When | Needs |
| --- | --- | --- |
| `azure-cli` (default) | almost always: reuses the sign-in you already have | `az login`; tokens are requested per tenant, so `az use` is optional |
| `interactive` | for the PIM commands on Entra roles and groups, whose scopes the Azure CLI's sign-in never carries | `client_id` of your own public client app; signs you in in a browser |
| `device-code` | the same, over SSH, in WSL, in a container, or anywhere without a browser | `client_id` of the same app; you enter a code at the device login page |

With `azure-cli`, the Azure CLI keeps your sign-in and renews it; when it lapses, the tool
offers to sign you back in (see [Token expiry](#token-expiry-and-signing-in-again)).
`interactive` and `device-code` sign you in once, then keep that sign-in in a private file,
so later commands (and other APIs) do not ask again; see
[Keeping a sign-in between commands](#keeping-a-sign-in-between-commands). On a headless
machine, use `device-code`.

#### Automation

Unattended jobs can run the same commands with an identity of their own:

| `auth` | For | Needs |
| --- | --- | --- |
| `client-secret` | a job with an app registration and a secret | `client_id`, and the secret in `AZURE_CLIENT_SECRET` |
| `workload-identity` | CI and Kubernetes, with no secret at all | `client_id`, and a federated token from `AZURE_FEDERATED_TOKEN_FILE` or the GitHub Actions OIDC endpoint |
| `managed-identity` | code running on an Azure host | nothing, or `client_id` for a user-assigned identity |

These have no sign-in to lapse: every token is a fresh exchange, and workload identity
asks for a new federated token each time, so a long job never runs into an expired one.
The environment variable names are the ones the Azure SDKs use, so a job configured for
one works for the other. In GitHub Actions, give the job `permissions: id-token: write`
and add a federated credential to the app registration whose subject matches the workflow:

```yaml
permissions:
  id-token: write
  contents: read

steps:
  - run: uv tool install git+https://github.com/libre-devops/python-helpers
  - run: ldo --config .github/ldo.toml entra app-credentials -p ci --expiring 30d
```

### Token expiry and signing in again

Signing in as yourself gives two things, and only one of them ever needs you:

- **Access tokens** last about an hour. The tool never holds on to one: each request asks
  for a current token, which is renewed five minutes before it expires, so a two-hour
  `devices watch` carries on across renewals by itself. If an API still answers 401 (a
  token revoked or expired early), the cached token is dropped and the request retried once.
- **Your sign-in** (the refresh token behind them) renews those tokens without asking, for
  days or weeks. But Entra ID ends it in cases no code can get around, by design:

| Cause | Entra ID code | Happens again? |
| --- | --- | --- |
| a Conditional Access sign-in frequency policy (every 8 hours, say) | AADSTS70043, AADSTS70044 | yes, on that schedule |
| the session went unused for too long (90 days) | AADSTS700082 | only after a long gap |
| a password change or expiry | AADSTS50132, AADSTS50133, AADSTS50055 | no |
| the session was revoked by an administrator or "sign out everywhere" | AADSTS50173 | no |
| multi-factor authentication newly required, expired, or not set up | AADSTS50076, AADSTS50078, AADSTS50079 | depends on the policy |

When that happens to the Azure CLI's sign-in, the error names the cause. On a terminal,
the tool also offers to sign the Azure CLI back in to that tenant there and then, and
carries on with the command; afterwards it puts back whichever account was active, since
`az login` changes it for every shell. A `devices check` or `watch` asks between passes,
never from its parallel workers, and repeats a pass that a lapse interrupted. Scripts and
CI never see the question: without a terminal the error is raised as before.
`LDO_REAUTH=device-code` signs in with a device code instead of a browser, and
`LDO_REAUTH=off` never asks.

`interactive` and `device-code` profiles sign in again by themselves when their refresh
token is refused, and say why.

### Keeping a sign-in between commands

An `interactive` or `device-code` profile keeps its refresh token after the command ends,
so the next command signs in without asking, until Entra ID ends the sign-in for one of
the reasons above. Access tokens are never kept, only the refresh token. By default it
goes in a private file, which works on a headless machine as well as a desktop;
`token_cache` on the profile picks somewhere else:

```toml
[microsoft.profiles.pim]
tenant_id = "<guid>"
auth = "device-code"
client_id = "<your public client app>"
# token_cache = "file"      the default
# token_cache = "keychain"  on a desktop with a keychain
# token_cache = "memory"    keep nothing: sign in for every command
```

| `token_cache` | Kept | Who can use it | Use it on |
| --- | --- | --- | --- |
| `file` (the default) | `~/.local/state/ldo/refresh-tokens.json` (`%LOCALAPPDATA%\ldo` on Windows), mode 0600 | anyone who can act as your account, root, and anyone with a copy (a backup) | your own machines, headless or not |
| `keychain` | macOS Keychain, or the Secret Service (GNOME Keyring, KWallet) on Linux; on Windows, a file encrypted with DPAPI | your account, while it is unlocked | a desktop, where you want it locked away |
| `memory` | nowhere; gone when the command ends | nobody | shared machines and jump hosts |

A refresh token is as good as your sign-in to that app until it expires or is revoked.
The default makes the trade the Azure CLI already makes on Linux, where it keeps its own
tokens in a plain file: fine on a machine that is yours, not on one other people log in
to as you, or can read the disk of. Set `memory` on shared machines. A cache file other accounts can read is refused
rather than used, as ssh refuses a readable key. The next sign-in then replaces it with a
private one.

- `keychain` on macOS and Linux needs the optional `keyring` package:
  `uv tool install "libre-devops-helpers[keychain] @ git+https://github.com/libre-devops/python-helpers"`.
  Windows needs nothing extra, since Credential Manager's size limit is too small for a
  refresh token and DPAPI is built in.
- `ldo entra sign-out -p <profile>` forgets the kept sign-in. Signing out of Entra ID
  itself, on every device, is done from your account's security settings.
- `LDO_TOKEN_CACHE` names a different file for `file` (and, with a `.dpapi` suffix, for
  `keychain` on Windows), for example a volume in a container.
- The Azure CLI keeps its own sign-in, and the other methods have no refresh token, so
  `token_cache` is refused on any other `auth`.

On a headless machine, use `device-code`: you get a code to enter from any browser,
anywhere. An `interactive` profile switches to a device code by itself when no browser
can be opened (as the Azure CLI does), since the browser's redirect could never reach a
headless machine; the app registration then needs "Allow public client flows" turned on,
which the setup below does. The offer to sign the Azure CLI back in works headless too:
`az login` falls back to a device code in the same way.

Two things are worth knowing. The Azure CLI hands out its own cached token until it
expires, so after activating a role in PIM you may keep the old token (and the old
permissions) for up to an hour; an `interactive` or `device-code` profile starts each
command with a new one. And a 401 with a claims challenge (continuous access evaluation,
after a revocation or a policy change) needs a fresh sign-in too; the error says so.

### Delegated sign-in (your own app registration)

The Azure CLI's token carries scopes Microsoft chose, and the PIM and incident ones are not
among them. Register a public client app once per tenant and grant it the delegated read
scopes, then point a profile at it. An administrator grants consent once:

```bash
app=$(az ad app create --display-name "ldo (delegated sign-in)" \
  --public-client-redirect-uris http://localhost --is-fallback-public-client true \
  --query appId -o tsv)
graph=00000003-0000-0000-c000-000000000000       # Microsoft Graph
arm=797f4846-ba00-4fd7-ba43-dac1f8f63013         # Azure Service Management
for scope in Directory.Read.All RoleEligibilitySchedule.Read.Directory \
  RoleAssignmentSchedule.ReadWrite.Directory RoleManagementPolicy.Read.Directory \
  PrivilegedEligibilitySchedule.Read.AzureADGroup PrivilegedAssignmentSchedule.ReadWrite.AzureADGroup \
  RoleManagementPolicy.Read.AzureADGroup SecurityIncident.Read.All ThreatHunting.Read.All; do
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

---

## Commands

```bash
ldo welcome                             # the banner, the config file, and what to run next
ldo profiles                            # every profile, which is active, and its sign-in
ldo az use test-tenant                  # switch az to a profile (signs in when needed)
ldo az whoami                           # az's active account and matching profile
ldo entra token graph -p prod-tenant    # get a token and check what it can do
pbpaste | ldo entra inspect-token --resource graph
ldo entra sign-out -p pim               # forget a kept sign-in (token_cache)
```

### Devices across Entra, Defender and Intune

```bash
ldo devices check web01,web02,db01                       # in Entra and onboarded to Defender?
ldo devices check -f plan.csv --column FQDN --tag linux-servers --group "MDE Pilot Devices"
ldo devices check -f plan.xlsx --column FQDN --sheet "Ring 1" --tag linux-servers
ldo devices watch -f hosts.txt --interval 5m --timeout 2h # poll until all complete
ldo devices watch web01 --max-passes 12 --active --compliant
ldo devices show web01.corp.example.com                  # one device, and what looks wrong
ldo devices av-signature web01,db01                       # Defender Antivirus versions
ldo device av-signature -f plan.xlsx --column FQDN --at-least 1.419.120.0
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

`av-signature` shows each device's Defender Antivirus signature, engine and platform
versions, its antivirus mode (active, passive or EDR block) and Defender's own "definitions
up to date" check, from one built-in Advanced Hunting query over `DeviceTvmInfoGathering` and
`DeviceTvmSecureConfigurationAssessment`. It runs through Graph like `xdr hunt`, or through
the Defender for Endpoint API with `--endpoint`, which the Azure CLI's sign-in can use.
`--at-least VERSION` flags older signatures, and `--show-query` prints the KQL to paste into
the portal instead. It exits 3 when a device is not found, is out of date, or is older than
`--at-least`. `ldo device` works as well as `ldo devices`.

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
ldo xdr hunt "EmailEvents | where Timestamp > ago(1d) | take 50" --timespan 7d
ldo xdr hunt "DeviceInfo | take 10" --endpoint   # the device tables, with the Azure CLI's sign-in
```

`xdr hunt` goes through Microsoft Graph (`runHuntingQuery`), which covers every Defender XDR
table: devices, email, identity, cloud apps and alerts. It needs `ThreatHunting.Read.All`,
which the Azure CLI's token never has, so use an `interactive` or `device-code` profile
whose app has it. `--endpoint` uses the Defender for Endpoint API instead: device tables
only, but the Azure CLI's sign-in works with it, through your Defender role.

### Incidents: Defender XDR, with Sentinel

In the unified security operations platform (the Defender portal), Microsoft Sentinel's
incidents land in the same queue as Defender's, so these read both:

```bash
ldo xdr incidents top                          # today's open incidents, most severe first (10)
ldo xdr incidents top --severity high -n 20
ldo xdr incidents latest                       # the newest, any status, from the last 30 days
ldo xdr incidents latest --source sentinel     # only incidents with Sentinel alerts
ldo xdr incidents list --from 2026-09-01 --to 2026-09-24   # between days, both whole
ldo xdr incidents list --yesterday --status resolved
ldo xdr incidents list --since 6h --updated    # updated, rather than created, in the last 6 hours
ldo xdr incidents summary --since 7d           # counts by severity, status and source
ldo xdr incidents show 12345                   # alerts, devices, users and the portal link
```

Every command takes the same window: `--today`, `--yesterday`, `--since 7d`, or `--from`
and `--to` (days in your local time, `YYYY-MM-DD`, `today` or `yesterday`; either end may
be left out). `--updated` windows on the last update instead of creation. Filters:
`--status` (`open`, `active`, `in-progress`, `awaiting-action`, `resolved`, `redirected`,
`all`; repeatable), `--severity` (at least: `informational`, `low`, `medium`, `high`),
`--source` (repeatable: `sentinel`, `endpoint`, `identity`, `office`, `cloud-apps`,
`cloud`, `xdr`, `entra`, `app-governance`, `dlp`, `insider-risk`), and `-n` for how many.

An incident's source is the service behind its alerts, so `--source` is matched after
Graph returns the window. The incidents come from the Graph security API, which needs
`SecurityIncident.Read.All` on the token: the Azure CLI's token never has it, so use an
`interactive` or `device-code` profile whose app does (see
[Delegated sign-in](#delegated-sign-in-your-own-app-registration)), and a Defender XDR
role such as Security Reader. A Sentinel workspace that is not onboarded to the Defender
portal keeps its incidents to itself; `ldo logs query` reads its `SecurityIncident` table.

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

### Microsoft Graph

A fast way to read Graph with a profile's sign-in, as `az rest` would, but knowing Graph:

```bash
ldo graph whoami                     # who the token is for, its scopes or roles, when it expires
ldo graph token --raw                # a checked Graph token, for curl or a script
ldo graph get me
ldo graph get users --select id,displayName,userPrincipalName --all -o csv
ldo graph get users --filter "startswith(displayName,'Ana')" --count
ldo graph get users --search "displayName:ana"   # quoted for you, with ConsistencyLevel
ldo graph get devices --top 50 --limit 200
ldo graph get "https://graph.microsoft.com/beta/me/memberOf"   # pasted from Graph Explorer
ldo graph get security/alerts_v2 --beta
ldo graph get-user ana@example.com   # by UPN, id or display name
ldo graph get-device web01.corp.example.com      # FQDN, then short name, as elsewhere
ldo graph get-group "MDE Pilot Devices"
ldo graph get-app billing-api        # by name, object id or app id
ldo graph get-sp "Microsoft Graph"
ldo graph hunt "IdentityLogonEvents | take 10"   # the same as xdr hunt
```

`get` takes a path (`users`, `/me/memberOf`, `beta/...`) or a full Graph URL, and shows one
page unless you pass `--all` or `--limit`, saying when there are more. `--count` and
`--search` send `ConsistencyLevel: eventual` for you, and `--eventual` sends it for other
advanced queries. Collections come back as rows (the familiar columns in a table, or those
you `--select`), and single objects as their fields; `-o json` gives Graph's records whole.
The token is only ever sent to the profile's Graph host, and every command reads: there is
no POST, PATCH or DELETE.

What a Graph call may read depends on the token's scopes: `ldo graph whoami` lists them. The
Azure CLI's token reads the directory, users, groups and devices; the security APIs need a
profile whose app has their scopes.

### Logic Apps

Tooling for Consumption Logic App workflows, Sentinel playbooks among them, ported from the
LogicApps module in LibreDevOpsHelpers. Most of it reads files and never touches the
network: it checks a definition against what Azure actually rejects, or accepts and then
fails on when the workflow runs.

```bash
ldo logicapp check templates/                        # every .json and .json.tftpl in the folder
ldo logicapp check router.json --connection azuresentinel --supplied tenant_id --strict
ldo logicapp params export.json --unsatisfied        # which parameters will have no value
ldo logicapp references dist/ --unwired              # connection keys used but never wired
ldo logicapp connections export.json                 # resolved connections, managed identity or not
ldo logicapp order dist/                             # the deploy order, from dispatch actions
ldo logicapp diff dist/router.json raw/router.json   # rendered template against what is deployed
ldo logicapp defaults export.json --out portable.json
ldo logicapp rewrite export.json --replace /subscriptions/aaa=/subscriptions/bbb --replace rg-old=rg-new
ldo logicapp export -g rg-soc-uks-dev-01 --out raw/  # deployed workflows to files (reads only)
ldo logicapp validate export.json -g rg-soc-uks-dev-01   # Azure's verdict; nothing is deployed
```

What the checks encode, and why:

- **Shapes.** A definition arrives as the designer's code view (`definition` and
  `parameters`), an ARM resource GET (`properties.definition`), or a template's bare
  definition. A wrapper's `parameters` holds values; a bare definition's holds
  declarations. Every command unwraps first, so this never trips anything up, and `diff`
  compares a code view with an ARM GET of the same workflow cleanly.
- **Templates.** `.json.tftpl` files are read with their `${...}` tokens blanked, so their
  shape can be checked without rendering. `$${` is the escaped literal, and `@{...}` Logic
  App expressions are left alone.
- **Parameters.** Every declared parameter needs a value by deploy time (`InvalidTemplate`
  otherwise): from a `defaultValue`, the wrapper, `--supplied` (what a deployment tool
  passes, such as a Terraform module's parameters input), or, for `$connections`, the
  deployment tool itself. A SecureString or SecureObject is never taken from the wrapper:
  pass it as an input so the secret stays out of the definition.
- **Connections.** A definition names each connection by an arbitrary key, and nothing
  checks it matches the key wired at deploy time: it saves, deploys, and fails when it
  runs. `references` finds every key used, in triggers (a Sentinel incident trigger, say)
  and nested actions, and says whether the wrapper wires it.
- **Order.** Azure checks a native Workflow dispatch action's target when the caller is
  written (`NestedWorkflowNotFound`), so a caller deploys after what it calls. `order`
  works that out from the dispatch actions themselves (inside Switch cases too), and not
  from a workflow merely naming a sibling.

`check` exits 3 on any error (with `--strict`, any warning too), as do `references` with an
unwired key, `diff` with a difference, and `validate` with a rejection, so each can gate a
pipeline. `validate` posts the definition to the resource provider's validate endpoint, which
type-checks the whole of it and creates nothing: the authority the offline checks defer to.

### Common options

- `-p/--profile` (or `LDO_PROFILE`) picks the profile. Without it, the vendor section's
  `default_profile` is used, then (for Microsoft) the Azure CLI's active account.
- `-o/--output` is `table` (the default), `json` (the services' full records, for `jq`) or
  `csv` (for spreadsheets). Data goes to stdout; notes, warnings and progress go to stderr.
- Commands that take names accept `"a,b,c"`, several arguments, `-` to read stdin, and
  `-f/--from-file`: one name per line (with `#` comments), or a column of a CSV or Excel
  workbook (`.xlsx`, `.xlsm`, `.xltx`, `.xltm`) named by `--column`. The header is matched
  case-insensitively, and may sit below title rows. In a workbook, `--sheet` picks the tab;
  without it, the one visible sheet with that column is used (several is an error that
  lists them), or the first visible sheet when no column is named. Values are read as Excel
  saved them: formulas are not recalculated and macros never run. Rows hidden or filtered
  out in Excel are still read, with a warning saying how many. Legacy `.xls`, `.xlsb` and
  `.ods` files, and password-protected workbooks, are refused with a hint to save as
  `.xlsx` or `.csv`.
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

---

## ServiceNow

The `snow` commands sign in to a ServiceNow instance as you, and read from it:

```bash
ldo snow sign-in                  # sign in once; the sign-in is kept
ldo snow whoami                   # who you are, your roles, which features they cover
ldo snow instance                 # the release, and whether Security Incident Response is there
ldo snow apps security --all      # applications (store and custom), active or not
ldo snow token --raw              # an access token, for curl or a script
ldo snow sign-out                 # forget the kept sign-in
```

### Signing in: OAuth

Sign-in is OAuth, through an OAuth application registry entry on the instance. You sign
in once; the tool keeps the refresh token (in the private file, as for Microsoft; see
[Keeping a sign-in between commands](#keeping-a-sign-in-between-commands)), and every
later command signs in by itself until it lapses, 100 days by default. Two ways to sign
in, set by `sign_in` on the profile:

- `browser` (the default): the tool shows a link. Open it in any browser, on any machine,
  and sign in as you do to the instance: single sign-on and MFA work as usual. The browser
  then lands on `http://localhost:8765/callback?code=...`; the page will not load, which
  is expected. Copy that address and paste it back. This works on a headless machine, and
  at a workplace that does not allow passwords on the API.
- `password`: your username and password, once, from `SNOW_INSTANCE_PASSWORD` or asked for.
  For a developer instance, or any account with a local ServiceNow password.

The client id comes from the profile or `SNOW_CLIENT_ID`; the client secret from
`SNOW_CLIENT_SECRET`, or `ldo snow sign-in` asks for it (hidden) and keeps it with the
sign-in, so it is not needed again. There is deliberately no option to pass a secret on
the command line, where it would land in your shell history and the process list.

Without a config file, the environment is enough:

```bash
export SNOW_INSTANCE_URL=https://dev12345.service-now.com
export SNOW_CLIENT_ID=<client id>
ldo snow sign-in    # asks for the secret, shows the link, and keeps the sign-in
ldo snow whoami
```

or in the config file, one profile per instance:

```toml
[servicenow]
default_profile = "work"

[servicenow.profiles.work]
instance = "https://yourcompany.service-now.com"
client_id = "<client id>"

[servicenow.profiles.dev]
instance = "dev12345"          # short for https://dev12345.service-now.com
client_id = "<client id>"
sign_in = "password"
username = "admin"
```

### Setting up the application registry entry

Someone with admin on the instance makes it once, and everyone signs in through it:

1. All > System OAuth > Application Registry > New > **Create an OAuth API endpoint for
   external clients**.
2. **Name**: anything, for example `ldo`.
3. **Client Secret**: leave it empty and one is generated. After saving, open the record
   again to copy the Client ID and the Client Secret.
4. **Redirect URL**: `http://localhost:8765/callback`, exactly. Browser sign-in sends you
   there; a profile's `redirect_uri` changes it, and must then match.
5. **Refresh Token Lifespan**: how long a sign-in lasts before you sign in again. The
   default, 8,640,000 seconds (100 days), is fine; shorten it if your policy wants.
6. **Access Token Lifespan**: leave the default, 1,800 seconds. The tool renews access
   tokens itself.
7. **Active**: ticked. Leave **Public Client** unticked: the tool uses the secret.

The same entry serves both `browser` and `password` sign-in. A token can do what your
account can, no more: the instance's roles and access controls decide.

### Basic sign-in

`auth = "basic"` sends the username and password with every request. ServiceNow now
refuses that for interactive accounts: an instance answers 401 even though the same
password works in the browser, unless the account holds the `snc_basic_auth_api_access`
role, or is a "web service access only" account. Prefer OAuth.

### Security Incident Response on a developer instance

A personal developer instance does not have Security Incident Response until you add it.
`ldo snow instance` says whether it is there (it looks for the `sn_si_incident` table),
and `ldo snow apps security` lists it once installed. To add it: on developer.servicenow.com, open
your instance's menu and choose **Activate Plugin**, then find Security Incident Response.
If it is not offered there, sign in to the instance as admin and install it from All >
System Applications > All Available Applications, with its demo data if you want records
to work with. Then `ldo snow instance` shows it installed.

---

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
| `xdr ...` (but `hunt`), `--defender`, `--tag` | Defender | `Machine`, `Alert`, `Vulnerability`, `Ti` and `AdvancedQuery` read permissions, or a Defender role for delegated access | yes, through your Defender role |
| `xdr hunt`, `graph hunt`, `devices av-signature` | Graph | `ThreatHunting.Read.All`, and a Defender XDR role | no; `--endpoint` does, for the device tables |
| `graph get ...`, `get-user`, `get-device`, `get-group`, `get-app`, `get-sp` | Graph | whatever the path reads; `ldo graph whoami` shows what the token carries | directory, users, groups, devices and apps: yes |
| `azure ...` | ARM | Azure RBAC Reader | yes |
| `keyvault expiry` | Key Vault | Key Vault Reader (data plane), and a firewall that allows your address | yes |
| `logs query` | Log Analytics | Log Analytics Reader on the workspace | yes |
| `pim ... --azure` | ARM | Azure RBAC read at the scope; Entra ID P2 in the tenant | yes |
| `pim ... --entra` | Graph | `RoleEligibilitySchedule.Read.Directory`, `RoleAssignmentSchedule.ReadWrite.Directory` (Graph requires ReadWrite to list requests), `RoleManagementPolicy.Read.Directory` | no |
| `pim ... --groups` | Graph | `PrivilegedEligibilitySchedule.Read.AzureADGroup`, `PrivilegedAssignmentSchedule.ReadWrite.AzureADGroup`, `RoleManagementPolicy.Read.AzureADGroup` | no |
| `xdr incidents ...` | Graph | `SecurityIncident.Read.All`, and a Defender XDR role such as Security Reader | no |
| `logicapp export` | ARM | Azure RBAC read on the workflows (Logic App Reader, or Reader) | yes |
| `logicapp validate` | ARM | `Microsoft.Logic/locations/workflows/validate/action` (Logic App Contributor has it) | yes |

For the rows marked no, use a profile with its own app registration granted the
permission: `interactive` or `device-code` to sign in as yourself (see
[Delegated sign-in](#delegated-sign-in-your-own-app-registration)), or, for automation,
`client-secret` or `workload-identity`. `ldo entra token graph` shows which features a
token can serve, one line each.

### What the token checks mean

`entra token` and `entra inspect-token` decode the token and check expiry, not-before, that
the issuer matches the token's tenant, the audience against the API, and the tenant against
the profile. For each feature that uses the API, they report whether the token's scopes or
roles cover it (a warning, since delegated access can also come from the service's own RBAC).
The signature is **not** verified: this answers "is this the token I meant to get?", not "is
this token genuine?". The token value is never printed unless you pass `--raw`, and never
logged.

---

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
grows. The README's logo, badges and footer point at Libre DevOps and this repository's
GitHub pages, so replace them with your own by hand.

---

## Using it as a library

The code is layered, and a test enforces the layering:

| Package | Depends on | What it holds |
| --- | --- | --- |
| `core` | nothing | vendor-neutral: errors, the config file, the brand, the token cache, HTTP client (retries, Retry-After, paging), command runner, polling, input parsing, query results, logging |
| `microsoft` | `core` | shared Microsoft layer: clouds, APIs as tokens see them, token checks, credentials, the Azure CLI runner, `[microsoft]` profiles |
| `microsoft.azcli` | `core`, `microsoft` | Azure CLI accounts, sign-in and profile switching |
| `microsoft.entra` | `core`, `microsoft` | devices, users, groups, roles, sign-ins, app credentials, Conditional Access |
| `microsoft.xdr` | `core`, `microsoft` | Defender machines, alerts, vulnerabilities, indicators, Advanced Hunting (the endpoint API) |
| `microsoft.graph` | `core`, `microsoft` | Microsoft Graph directly: any GET with paging, objects by name or id, Advanced Hunting over the whole Defender XDR schema |
| `microsoft.incidents` | `core`, `microsoft` | Defender XDR incidents (Sentinel's included) through the Graph security API |
| `microsoft.logicapps` | `core`, `microsoft` | Consumption Logic App definitions: offline checks, export and validation |
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

---

## CI/CD

Every pull request and push to `main` runs `.github/workflows/ci.yml`:

| Job | What it does |
| --- | --- |
| Secret scan | gitleaks over every commit, with the checksum-pinned release; `.gitleaks.toml` allows only the public Microsoft endpoints and application ids the code holds |
| Lint | `ruff check` and `ruff format --check`, after `uv sync --locked` |
| Dependency audit | `pip-audit` over the locked, hashed dependency tree |
| Test | pytest on Python 3.11 to 3.14 on Linux, and 3.13 on Windows and macOS, including the rebrand test |
| Coverage | line and branch coverage, failing below the floor in `pyproject.toml` (`fail_under`), with the report in the job summary and the total written for the badge |
| Build | builds the sdist and wheel once, installs the wheel in a clean environment, and keeps both as the run's artifact |

`.github/workflows/container.yml` builds both images for `amd64` and `arm64` on every pull
request and push. It runs the native build (the version, a command's help, a non-root user,
and for the default image a signed-out `az whoami` that must fail cleanly) and scans it with
a checksum-pinned Trivy. The `slim` image
fails on any high or critical vulnerability that has a fix; the default image fails on a
fixed critical one and reports the rest, since the Azure CLI inside it pins its own
dependencies. Findings with a fix go to the Security tab. Those without one, mostly Debian
base packages still waiting on a fix from Debian, are kept with each run as a
`trivy-<variant>` artifact, and the weekly rebuild picks up each fix as Debian releases it.

After a passing run on `main`, `.github/workflows/badges.yml` commits the coverage total
to the `badges` branch as a shields.io endpoint file, which is where the README's coverage
badge reads it; nothing else lives on that branch.

CodeQL scans the Python code and the workflows on every change and weekly; Dependency
Review comments on pull requests that change dependencies. Third-party actions are pinned
to a commit.

### Patching

Updates reach the images by three routes, none of which needs anyone to remember:

1. **Debian packages.** Every Monday the container workflow rebuilds the latest release
   from its own source, on the same pinned base, applying the newest Debian security
   updates. It compares the packages with the published image and republishes only when
   one changed: the floating tags move to the patched build, which also gets its own
   stamped tag. It is scanned and gated like any other build first.
2. **Base images and Python.** Dependabot moves the digests of the `python` and `uv` base
   images when they are rebuilt upstream, and proposes new Python versions.
3. **Python dependencies and the Azure CLI.** Dependabot bumps the tool's lock file and
   `container/azure-cli/uv.lock`, and pip-audit checks the tool's.

Routes 2 and 3 land on `main` and ship with the next release, so cut a patch release after
merging them. If the Azure CLI pins a dependency with a fixed vulnerability, the fix can be
forced in `container/azure-cli/pyproject.toml` (see the comment there).

To release, set the version in `pyproject.toml` and `src/libre_devops_helpers/__init__.py`
(a test keeps them equal), merge, and push a tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

`.github/workflows/release.yml` runs the same CI as a gate, then builds, scans and pushes
both container images for every platform, with attestations, and only then publishes the
files the gate built (not a rebuild) as a GitHub release with `SHA256SUMS`, after checking
the tag matches the version. A release therefore never exists without its images.

---

## Development

```bash
just check           # ruff lint + format check + tests with coverage: what a change must pass
just coverage        # the tests with line and branch coverage, and what is missed
just test -k devices # extra args go to pytest
just test-311        # the suite on the oldest supported Python
just fmt             # apply formatting and safe lint fixes
just run welcome     # run the CLI from the working tree
```

The tests mirror the package: `tests/core`, `tests/microsoft/<feature>`, `tests/cli` and
`tests/cli/commands`, one test module per module under test, with shared fakes in
`tests/fakes`, one module per concern (`fakes.http`, `fakes.azcli`, `fakes.workbooks`, ...).
`tests/project` holds the tests of the project itself: the layering, the rebrand, this
layout. Tests never touch the network, a real `az`, or a real clock: HTTP goes through a fake
`requests` adapter, `az` through a fake subprocess runner, and polling through a fake clock,
so an hour-long watch runs in microseconds. Runtime dependencies are kept to `requests` and
`typer`; everything else, the credentials included, is the standard library.

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request, and
[SECURITY.md](SECURITY.md) to report a vulnerability.

---

## Licence

[MIT](LICENSE)

---

<div align="center">
<sub>
Part of <a href="https://libredevops.org">Libre DevOps</a>. Everything we publish is open and
provided as-is; review and test it against your own requirements before production use.
</sub>
</div>
