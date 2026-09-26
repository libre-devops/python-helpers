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
[![PyPI](https://img.shields.io/pypi/v/libre-devops-helpers?label=pypi&logo=pypi&logoColor=white&color=3775A9)](https://pypi.org/project/libre-devops-helpers/)
[![Container images](https://img.shields.io/badge/ghcr.io-python--helpers-2496ED?logo=docker&logoColor=white)](https://github.com/libre-devops/python-helpers/pkgs/container/python-helpers)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

</div>

---

`ldo` is a fast, read-only command line for day-to-day security and platform work across
Microsoft (Entra ID, Defender XDR, Intune, Azure, Graph, PIM, Logic Apps) and ServiceNow. It
signs in as you, through the Azure CLI by default, and can read only what you can. The Python
sibling of the [LibreDevOpsHelpers](https://github.com/libre-devops/powershell-helpers)
PowerShell module, and importable as a library too.

---

## Commands

| Command | What it does | Docs |
| --- | --- | --- |
| `ldo devices` | check a list of devices across Entra, Defender and Intune, watch until they are all there, show one, read Defender Antivirus versions | [devices](docs/devices.md) |
| `ldo entra` | devices and whether they are in a group, users, groups, roles, sign-ins, app credentials, Conditional Access; tokens | [entra](docs/entra.md) |
| `ldo intune` | managed devices: compliance, last sync, owner | [entra](docs/entra.md) |
| `ldo xdr` | Defender machines, alerts, vulnerabilities, indicators, Advanced Hunting, a device's timeline, custom detection rules (and their export to YAML) | [defender](docs/defender.md) |
| `ldo xdr incidents` | the Defender XDR queue, Sentinel's included: top, latest, between days, summary | [defender](docs/defender.md#incidents-sentinels-included) |
| `ldo graph` | any Graph GET, objects by name, `whoami`, a Graph token, hunting | [graph](docs/graph.md) |
| `ldo azure` | subscriptions, Resource Graph, role assignments, Defender for Cloud, splitting resource ids into their parts | [azure](docs/azure.md) |
| `ldo azure automation` | Automation accounts: runbook jobs, and each job's logs and output | [azure](docs/azure.md#automation) |
| `ldo keyvault` | secrets, certificates and keys close to expiry | [azure](docs/azure.md#key-vault) |
| `ldo logs` | KQL against a Log Analytics or Sentinel workspace, and which tables are receiving data | [azure](docs/azure.md#log-analytics) |
| `ldo pim` | eligible, active and standing access, requests, approvals, activation settings | [pim](docs/pim.md) |
| `ldo logicapp` | offline checks, export and validation for Consumption Logic Apps and Sentinel playbooks | [logic apps](docs/logic-apps.md) |
| `ldo snow` | ServiceNow: sign in, whoami, the instance, applications, a token | [servicenow](docs/servicenow.md) |
| `ldo az` | switch the Azure CLI between profiles | [signing in](docs/authentication.md) |
| `ldo network test` | test the way out through a corporate proxy: the proxy, the certificates, each service | [network](docs/network.md) |
| `ldo json` | pretty-print any JSON (`az rest ... \| ldo json`) in colour, or as YAML | [configuration](docs/configuration.md#json-yaml-and-logs) |
| `ldo profiles`, `ldo config` | your profiles, and the config file | [configuration](docs/configuration.md) |

Every command takes `-p` for a profile and `-o table|json|csv|tsv`, lists take `--sort` and
`--unique` by column, and lists of names come from arguments, stdin, a text file, or a
column of a CSV or Excel workbook.

---

## Install

From [PyPI](https://pypi.org/project/libre-devops-helpers/):

```bash
uv tool install libre-devops-helpers     # the ldo command, in an environment of its own
pipx install libre-devops-helpers        # the same, with pipx
uv pip install libre-devops-helpers      # into the current environment, to use it as a library
pip install libre-devops-helpers         # the same, with pip
uv tool upgrade libre-devops-helpers     # later, to the newest release
```

Add the `keychain` extra (`"libre-devops-helpers[keychain]"`) to keep sign-ins in the macOS
Keychain or the Linux Secret Service. A tagged release installs straight from GitHub too:
`uv tool install git+https://github.com/libre-devops/python-helpers@v0.6.2`.

Or run the container image, which has the Azure CLI inside:
`podman run --rm -it ghcr.io/libre-devops/python-helpers:latest --help`
(see [Container images](docs/containers.md)). Each release is also in the
[GitLab copy](https://gitlab.com/libre-devops/python-helpers)'s package and container
registries ([how](docs/development.md#gitlab-ci)).

---

## Quickstart

Sign in with the Azure CLI, and `ldo` works as you at once, in the tenant and subscription
`az` is using. Nothing else is needed.

```bash
az login
ldo az whoami                                   # who ldo reads as, and where
ldo devices check web01,web02                   # in Entra and onboarded to Defender?
ldo xdr alerts --since 24h --severity high
```

A profile for each tenant or subscription you work in is optional: `ldo config init`, then
see [Configuration](docs/configuration.md).

### Checking a change from its plan

Give it the plan: the workbook, the sheet, the column of names, and which rows to take. Here,
the servers changing today, which should end up in two Entra groups:

```bash
ldo devices check -f plan.xlsx --sheet "Ring 1" --column FQDN --where "Scheduled Date=today" \
  --group "Linux servers" --group "Linux pilot"
ldo devices watch -f plan.xlsx --sheet "Ring 1" --column FQDN --where "Scheduled Date=today" \
  --group "Linux servers" --group "Linux pilot" --interval 5m --timeout 4h
```

`check` looks once; `watch` looks again every `--interval` until every server meets every
expectation, and exits 0 then, or 3 when `--timeout` comes first. Each row says how many
checks the server meets (MET): `--sort met:desc` puts the complete ones first. `--where`
takes a day (`25/09/2026`, `tomorrow`) or a span (`last 7d`,
`2026-09-01..2026-09-14`); see [lists of names](docs/configuration.md#options-every-command-takes)
and [check and watch](docs/devices.md#check-and-watch).

More:

```bash
ldo devices av-signature -f plan.xlsx --column FQDN   # Defender Antivirus versions
ldo entra devices -f plan.xlsx --column FQDN --group "Linux pilot"
ldo azure automation logs aa-ops --runbook Rotate-Keys    # the newest run's logs
ldo azure resource-graph "resources | summarize count() by type"
ldo keyvault expiry kv-app-prd --within 30d
```

Incidents, Graph hunting and PIM for Entra roles need scopes the Azure CLI's token never
has: sign in through [your own app registration](docs/authentication.md#your-own-app-registration)
for those. [Permissions](docs/permissions.md) lists what each command needs.

---

## Documentation

- [Configuration](docs/configuration.md): profiles, common options, environment variables, exit codes
- [Proxies and certificates](docs/network.md): corporate proxies, cntlm, TLS inspection
- [Signing in](docs/authentication.md) and [Permissions](docs/permissions.md)
- [Container images](docs/containers.md)
- [Using it as a library](docs/library.md) and [Rebranding](docs/rebranding.md) for your organisation
- [Development](docs/development.md): `just` recipes, tests, CI and releasing
- [AI.md](AI.md): the instructions for AI coding assistants (Claude Code, Copilot, Codex, Kiro)

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md), and
[SECURITY.md](SECURITY.md) to report a vulnerability. Licensed under [MIT](LICENSE).

---

<div align="center">
<sub>
Part of <a href="https://libredevops.org">Libre DevOps</a>. Everything we publish is open and
provided as-is; review and test it against your own requirements before production use.
</sub>
</div>
