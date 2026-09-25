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
# proxy = "127.0.0.1:3128"             # behind a corporate proxy, e.g. cntlm (see network.md)
# ca_bundle = "~/certs/proxy-ca.pem"   # a TLS-inspecting proxy's root, when not in the OS store

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

ServiceNow profiles are described in [ServiceNow](servicenow.md#configuration). The
top-level `proxy`, `no_proxy` and `ca_bundle` apply to every call, and to the Azure CLI; see
[Proxies and certificates](network.md).

## Options every command takes

| Option | Meaning |
| --- | --- |
| `-p`, `--profile` | The profile, or `LDO_PROFILE`. Without it: the section's `default_profile`, then (for Microsoft) the Azure CLI's active account. |
| `-o`, `--output` | `table` (the default), `json` (the services' full records, for `jq`), `csv` (with a header, for spreadsheets) or `tsv` (values only, no header, as `az -o tsv`, for `cut` and `while read`). Data goes to stdout; notes and progress to stderr, so `-o csv > file.csv` writes a clean file. |
| `--sort COLUMN[:desc]` | Sort the rows by a column, named as the table heads it (case, spaces and underscores do not matter: `"last seen"`, `last_seen`). Repeat it to sort by more, most significant first. Numbers, versions, severities (`Low` to `Critical`) and dates sort as such, and blanks go last either way. On every list, for the table, CSV and TSV. |
| `--unique COLUMN` | Keep only the first row for each value of a column, ignoring case; repeat it to keep one of each combination of several. It runs after `--sort`, so `--sort "last seen:desc" --unique device` keeps each device's newest record. For JSON, use `jq`'s `sort_by` and `unique_by`. |
| `--colour`, `--no-colour` | Colour, or none, whatever the output is (also spelt `--color`, `--no-color`); before the command, e.g. `ldo --colour xdr machines web01 \| less -R`. By default colour shows on a terminal, unless `NO_COLOR` is set; `FORCE_COLOR` turns it on. |
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
ldo xdr vulns web01 --sort severity:desc --sort cvss:desc
ldo xdr machines -f hosts.txt --sort "last seen:desc" --unique device -o csv > seen.csv
```

**Queries** (`xdr hunt`, `graph hunt`, `azure resource-graph`, `logs query`) come from the
argument, `--file`, or stdin.

## JSON, YAML and logs

What `-o json` writes is kept stable: keys are snake_case (a service's own records keep the
service's names), true and false are booleans, and a key is not renamed or dropped without
an entry in the [changelog](../CHANGELOG.md). A test holds every command to it.

`-o json` is indented, and coloured on a terminal: keys, strings, numbers and booleans each
have a colour, and brackets take the banner's rainbow by how deeply they nest, so a pair
shares one. Piped into `jq` or a file, it is plain JSON. `NO_COLOR` turns the colour off.

`ldo json` does the same for JSON from anywhere else, from stdin or a file, and reads JSON
Lines (one document per line) too:

```bash
az rest --url "https://graph.microsoft.com/v1.0/me" | ldo json
ldo json response.json --sort-keys
ldo graph get me -o json | ldo json --yaml       # as YAML
ldo json events.jsonl --compact                  # one line each
ldo json big.json --colour | less -R             # keep the colour through a pager
```

`--yaml` writes YAML, quoting any string a YAML reader could take for something else (`yes`,
`no`, `null`, `1.0`, `2026-09-24`, `@odata.context`), and writing multi-line strings as `|`
blocks. It needs nothing beyond the standard library. It only converts from JSON; there is
no YAML to JSON.

## OpenTelemetry logs

Logs go to stderr, so they never mix with data. `-v` and `-vv` turn them on as text.
`--log-format otlp` (or `LDO_LOG_FORMAT=otlp`) writes OpenTelemetry instead, in the
[OTLP file format](https://opentelemetry.io/docs/specs/otel/protocol/file-exporter/): JSON
Lines, each line a complete OTLP/JSON `LogsData` holding one record, as `Write-LdoLog` writes
in LibreDevOpsHelpers. In that mode stderr holds nothing else: the notes, warnings and errors
`ldo` would print become records too (notes at INFO, so `LDO_LOG_LEVEL=info` to keep them),
and an error's hint is an attribute.

```bash
LDO_LOG_FORMAT=otlp LDO_LOG_LEVEL=info ldo devices check -f hosts.txt 2>> /var/log/ldo/ldo.jsonl
```

| Variable | Becomes |
| --- | --- |
| `LDO_SERVICE_NAME`, else `OTEL_SERVICE_NAME` | the resource's `service.name` (default `ldo`) |
| `LDO_SERVICE_VERSION` | `service.version` (default the tool's version) |
| `LDO_DEPLOYMENT_ENVIRONMENT` | `deployment.environment.name` |
| `OTEL_RESOURCE_ATTRIBUTES` | more resource attributes, `key=value,key=value` |
| `LDO_TRACE_ID`, `LDO_SPAN_ID` | every record's `traceId` and `spanId`, so one run's logs join a trace |
| `LDO_CORRELATION_ID` | a `correlation_id` attribute, and the `traceId` when it is a GUID and no trace id is set |

An id that is not hex of the right width (dashes are dropped, so a GUID makes a trace id) is
left out, never sent: a collector rejects a whole payload with a bad one. Records carry
`code.function.name` and `code.line.number`, and a failure's `exception.type`,
`exception.message` and `exception.stacktrace`.

An OpenTelemetry Collector reads the file with the `otlp_json_file` receiver. From a
container, whose stdout and stderr the runtime writes to its own log files, read those with
`file_log` and turn our lines back into records with the `otlp_json` connector; it skips
the lines that are not OTLP, such as a table on stdout. Both are tested against Collector
0.161, which also accepts the older names `otlpjsonfile`, `filelog` and `otlpjson`, with a
warning.

```yaml
receivers:
  otlp_json_file:
    include: [/var/log/ldo/*.jsonl]
  file_log/containers:
    include: [/var/log/pods/*/ldo/*.log]    # the container named ldo, in any pod
    operators:
      - type: container          # unwrap the runtime's log format, add the pod's metadata
connectors:
  otlp_json:
exporters:
  otlp:
    endpoint: otel-backend.example.com:4317
service:
  pipelines:
    logs:
      receivers: [otlp_json_file, otlp_json]
      exporters: [otlp]
    logs/containers:
      receivers: [file_log/containers]
      exporters: [otlp_json]
```

## Environment variables

| Variable | Meaning |
| --- | --- |
| `LDO_CONFIG` | The config file. |
| `LDO_PROFILE` | The profile, as `--profile`. |
| `LDO_LOG_FORMAT`, `LDO_LOG_LEVEL` | As `--log-format` and `--log-level`. They mean the same for `Write-LdoLog` in LibreDevOpsHelpers, so one pipeline setting drives both. |
| `LDO_SERVICE_NAME`, `LDO_TRACE_ID` and the rest | What OTLP logs say about themselves; see [OpenTelemetry logs](#opentelemetry-logs). |
| `LDO_REAUTH` | When the Azure CLI's sign-in lapses on a terminal: unset asks to sign in again in a browser, `device-code` asks and uses a device code, `off` never asks. |
| `LDO_TOKEN_CACHE` | Another file for kept sign-ins, e.g. a container volume. |
| `LDO_PROXY_ADDRESS` | The proxy for `ldo` (and the Azure CLI it runs), winning over `proxy` and `HTTPS_PROXY`, e.g. `127.0.0.1:3129` for cntlm. |
| `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, `NO_PROXY` | As every tool reads them. See [Proxies and certificates](network.md). |
| `LDO_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` | A CA bundle to use exactly as it is, in place of the public roots with the OS store. |
| `LDO_NO_BANNER`, `NO_COLOR`, `FORCE_COLOR` | No banner; no colour; colour even when piped. The banner only ever shows on a terminal. |
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
