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
| `ldo xdr` | Defender machines, alerts, vulnerabilities, indicators, Advanced Hunting | [defender](docs/defender.md) |
| `ldo xdr incidents` | the Defender XDR queue, Sentinel's included: top, latest, between days, summary | [defender](docs/defender.md#incidents-sentinels-included) |
| `ldo graph` | any Graph GET, objects by name, `whoami`, a Graph token, hunting | [graph](docs/graph.md) |
| `ldo azure` | subscriptions, Resource Graph, role assignments, Defender for Cloud | [azure](docs/azure.md) |
| `ldo azure automation` | Automation accounts: runbook jobs, and each job's logs and output | [azure](docs/azure.md#automation) |
| `ldo keyvault` | secrets, certificates and keys close to expiry | [azure](docs/azure.md#key-vault) |
| `ldo logs` | KQL against a Log Analytics or Sentinel workspace | [azure](docs/azure.md#log-analytics) |
| `ldo pim` | eligible, active and standing access, requests, approvals, activation settings | [pim](docs/pim.md) |
| `ldo logicapp` | offline checks, export and validation for Consumption Logic Apps and Sentinel playbooks | [logic apps](docs/logic-apps.md) |
| `ldo snow` | ServiceNow: sign in, whoami, the instance, applications, a token | [servicenow](docs/servicenow.md) |
| `ldo az` | switch the Azure CLI between profiles | [signing in](docs/authentication.md) |
| `ldo json` | pretty-print any JSON (`az rest ... \| ldo json`) in colour, or as YAML | [configuration](docs/configuration.md#json-yaml-and-logs) |
| `ldo profiles`, `ldo config` | your profiles, and the config file | [configuration](docs/configuration.md) |

Every command takes `-p` for a profile and `-o table|json|csv`, and lists of names from
arguments, stdin, a text file, or a column of a CSV or Excel workbook.

---

## Install

```bash
uv tool install git+https://github.com/libre-devops/python-helpers@v0.4.1
```

Or run the container image, which has the Azure CLI inside:
`podman run --rm -it ghcr.io/libre-devops/python-helpers:latest --help`
(see [Container images](docs/containers.md)).

---

## Quickstart

```bash
az login                        # the default sign-in is the Azure CLI's
ldo config init                 # write ~/.config/ldo/config.toml
$EDITOR "$(ldo config path)"    # put your tenant id in a profile
ldo profiles                    # your profiles, and whether each can sign in
```

Then:

```bash
ldo devices check web01,web02                        # in Entra and onboarded to Defender?
ldo devices check -f plan.xlsx --column FQDN --tag linux-servers
ldo devices av-signature web01                       # Defender Antivirus versions
ldo entra devices -f plan.xlsx --column FQDN --group "MDE Pilot Devices"
ldo azure automation logs aa-ops --runbook Rotate-Keys    # the newest run's logs
ldo graph get-device web01
ldo xdr alerts --since 24h --severity high
ldo azure resource-graph "resources | summarize count() by type"
ldo keyvault expiry --all-vaults --within 30d
```

Incidents, Graph hunting and PIM for Entra roles need scopes the Azure CLI's token never
has: sign in through [your own app registration](docs/authentication.md#your-own-app-registration)
for those. [Permissions](docs/permissions.md) lists what each command needs.

---

## Documentation

- [Configuration](docs/configuration.md): profiles, common options, environment variables, exit codes
- [Signing in](docs/authentication.md) and [Permissions](docs/permissions.md)
- [Container images](docs/containers.md)
- [Using it as a library](docs/library.md) and [Rebranding](docs/rebranding.md) for your organisation
- [Development](docs/development.md): `just` recipes, tests, CI and releasing

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md), and
[SECURITY.md](SECURITY.md) to report a vulnerability. Licensed under [MIT](LICENSE).

---

<div align="center">
<sub>
Part of <a href="https://libredevops.org">Libre DevOps</a>. Everything we publish is open and
provided as-is; review and test it against your own requirements before production use.
</sub>
</div>
