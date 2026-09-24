# Configuration

[Back to the docs](README.md)

## The config file

```bash
ldo config init     # writes the template
ldo config path     # where it is
ldo profiles        # what it holds, which profile is active, and whether each can sign in
```

It lives at `~/.config/ldo/config.toml` (`%APPDATA%\ldo` on Windows), or wherever `--config`
or `LDO_CONFIG` points. It is created readable only by you, has a section per vendor, and
never holds a secret. Unknown keys are rejected, so a typo fails loudly.

```toml
# ca_bundle = "~/certs/proxy-ca.pem"   # a CA for every HTTPS call, behind a TLS-inspecting proxy

[microsoft]
default_profile = "prod-tenant"

[microsoft.profiles.prod-tenant]
description = "Production tenant"
tenant_id = "<tenant guid>"
workspace_id = "<Log Analytics workspace id>"   # the default for 'logs query'

[microsoft.profiles.prod]
tenant_id = "<tenant guid>"
subscription_id = "<subscription guid>"

[servicenow.profiles.work]
instance = "https://yourcompany.service-now.com"
client_id = "<client id>"
```

## Microsoft profiles

A profile is a tenant, optionally pinned to a subscription, with one way of getting tokens.

| Key | Meaning |
| --- | --- |
| `tenant_id` | Required. The tenant the profile acts in. |
| `subscription_id` | Pins the profile to one subscription; Azure commands then cover only it. |
| `auth` | How it signs in: `azure-cli` (the default), `interactive`, `device-code`, `client-secret`, `workload-identity` or `managed-identity`. See [Signing in](authentication.md). |
| `client_id` | The app registration, or user-assigned managed identity, to sign in with. |
| `token_cache` | Where an `interactive` or `device-code` profile keeps its sign-in: `file` (the default), `keychain` or `memory`. |
| `cloud` | `public` (the default), `usgov` (GCC High) or `china`. Point the Azure CLI at the same one with `az cloud set`. |
| `workspace_id` | The Log Analytics workspace for `logs query` without `--workspace`. |
| `mde_url` | A regional Defender for Endpoint endpoint, e.g. `https://api-eu.securitycenter.microsoft.com`. |

ServiceNow profiles are described in [ServiceNow](servicenow.md#configuration).

## Options every command takes

| Option | Meaning |
| --- | --- |
| `-p`, `--profile` | The profile, or `LDO_PROFILE`. Without it: the section's `default_profile`, then (for Microsoft) the Azure CLI's active account. |
| `-o`, `--output` | `table` (the default), `json` (the services' full records, for `jq`) or `csv`. Data goes to stdout; notes and progress to stderr. |
| `-v`, `-vv` | Info or debug logging, on stderr. |
| `--log-format` | `text`, `json` or `otlp` (one OTLP/JSON record per line, for a collector's `otlpjsonfile` receiver). |

**Lists of names** (devices, machines) come as `"a,b,c"`, several arguments, `-` for stdin,
or `-f` with a file: one name per line, or a column of a CSV or Excel workbook (`.xlsx`,
`.xlsm`, `.xltx`, `.xltm`) named by `--column`. The header may sit below title rows. In a
workbook, `--sheet` picks the tab; without it, the one visible sheet with that column is used.
Values are read as Excel saved them: no formulas are recalculated and no macros run.

```bash
ldo devices check web01,web02
ldo devices check -f plan.xlsx --column FQDN --sheet "Ring 1"
cat hosts.txt | ldo xdr machines -
```

**Queries** (`xdr hunt`, `graph hunt`, `azure resource-graph`, `logs query`) come from the
argument, `--file`, or stdin.

## Environment variables

| Variable | Meaning |
| --- | --- |
| `LDO_CONFIG` | The config file. |
| `LDO_PROFILE` | The profile, as `--profile`. |
| `LDO_LOG_FORMAT`, `LDO_LOG_LEVEL` | As `--log-format` and `--log-level`. They mean the same for `Write-LdoLog` in LibreDevOpsHelpers, so one pipeline setting drives both. |
| `LDO_REAUTH` | When the Azure CLI's sign-in lapses on a terminal: unset asks to sign in again in a browser, `device-code` asks and uses a device code, `off` never asks. |
| `LDO_TOKEN_CACHE` | Another file for kept sign-ins, e.g. a container volume. |
| `LDO_NO_BANNER`, `NO_COLOR` | No banner; no colour. The banner only ever shows on a terminal. |
| `AZURE_CLIENT_SECRET`, `AZURE_FEDERATED_TOKEN_FILE` | For `client-secret` and `workload-identity` profiles, as the Azure SDKs use them. |
| `SNOW_INSTANCE_URL`, `SNOW_CLIENT_ID`, `SNOW_CLIENT_SECRET`, `SNOW_INSTANCE_USERNAME`, `SNOW_INSTANCE_PASSWORD` | ServiceNow, with or without a config file. |

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | An error, or a token check failed (`--strict` fails on warnings too). |
| 2 | A usage error. |
| 3 | It ran, and found something that needs attention: a device short of an expectation, a watch that hit its limit, a credential close to expiry, an out-of-date signature. |
| 130 | Stopped with Ctrl-C. |

Code 3 lets a scheduled job alert on findings while still failing loudly on errors.
