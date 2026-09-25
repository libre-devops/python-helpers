# Using it as a library

[Back to the docs](README.md)

The code is layered by vendor, and a test enforces the layering:

| Package | Depends on | Holds |
| --- | --- | --- |
| `core` | nothing | errors, config, the brand, the token cache, the HTTP client (retries, Retry-After, paging), polling, input parsing, query results, logging, sorting, colour |
| `microsoft` | `core` | clouds, APIs as tokens see them, token checks, credentials, the Azure CLI runner, `[microsoft]` profiles |
| `microsoft.azcli` | `core`, `microsoft` | Azure CLI accounts, sign-in and profile switching |
| `microsoft.entra` | `core`, `microsoft` | devices, users, groups, roles, sign-ins, app credentials, Conditional Access |
| `microsoft.xdr` | `core`, `microsoft` | Defender machines, alerts, vulnerabilities, indicators, hunting (the endpoint API), device timelines |
| `microsoft.graph` | `core`, `microsoft` | any Graph GET with paging, objects by name or id, hunting over the whole XDR schema |
| `microsoft.incidents` | `core`, `microsoft` | Defender XDR incidents, Sentinel's included |
| `microsoft.detections` | `core`, `microsoft` | custom detection rules, and their export to the Terraform module's YAML |
| `microsoft.intune` | `core`, `microsoft` | managed devices and compliance |
| `microsoft.azure` | `core`, `microsoft` | subscriptions, Resource Graph, RBAC, Defender for Cloud |
| `microsoft.keyvault`, `microsoft.loganalytics` | `core`, `microsoft` | secret, certificate and key metadata; KQL against a workspace, and its ingestion |
| `microsoft.pim` | `core`, `microsoft` | PIM for Azure resources, Entra roles and groups |
| `microsoft.logicapps` | `core`, `microsoft` | Logic App definitions: offline checks, export, validation |
| `microsoft.devices` | the above, with `entra`, `xdr`, `intune` | device checks, watches, the combined view, antivirus versions |
| `servicenow` | `core` | ServiceNow profiles, OAuth, the Table API, the instance |
| `cli` | all of them | the `ldo` command: it parses, calls and renders, and nothing more |

Every client takes any token provider, so where tokens come from is up to you:

```python
from libre_devops_helpers.core import CachingTokenProvider
from libre_devops_helpers.microsoft import credential_for, load_config
from libre_devops_helpers.microsoft.devices import DeviceChecker, Expectations
from libre_devops_helpers.microsoft.entra import EntraClient
from libre_devops_helpers.microsoft.xdr import XdrClient

profile = load_config().get("prod-tenant")
tokens = CachingTokenProvider(credential_for(profile))

with (
    EntraClient.for_profile(profile, tokens) as entra,
    XdrClient.for_profile(profile, tokens) as xdr,
):
    run = DeviceChecker(entra=entra, xdr=xdr).check(
        ["web01", "web02"], Expectations(tags=("linux-servers",))
    )
    print(run.complete, [report.name for report in run.reports if not report.complete])
```

Library code raises `LdoError` subclasses and never exits; only the CLI turns errors into
messages and exit codes.

## Sorting, de-duplicating and colour

`core.sorting` sorts any records the way the tables do: numbers as numbers, versions part by
part, severities by rank, names naturally (`web2` before `web10`) and without case, and
blanks last whichever way a key runs. `unique` keeps the first of each value, so sorting
newest first and then keeping one per device keeps each device's newest record:

```python
from operator import attrgetter

from libre_devops_helpers.core.sorting import sort_records, unique

worst = sort_records(vulns, (attrgetter("severity"), True), (attrgetter("cvss"), True))
newest = unique(sort_records(machines, (attrgetter("last_seen"), True)), attrgetter("name"))
```

`core.colour` holds the one colour decision (`use`, `setting`, `wanted`: what was asked,
then `NO_COLOR`, then `FORCE_COLOR`, then whether it is a terminal), ANSI `style` and
`strip`, and `json_text`, which is `json.dumps` in colour. `colour.paint` colours
`core.yaml_text.dumps` the same way.

## What the process keeps

A few settings are the process's own, set once rather than passed to every call:

| Setting | Set by | What it does |
| --- | --- | --- |
| `core.network.configure(NetworkSettings(...))` | the CLI, from the config file | the proxy, `no_proxy` and `ca_bundle` for every call not given its own |
| `core.trust` | built on first use | the combined CA bundle, written once to your cache folder and reused; `trust.forget()` drops it |
| `core.colour.use(True / False / None)` | the CLI's `--colour` flag | whether anything written is coloured |

Without `configure`, calls follow the environment alone (`HTTPS_PROXY`, `NO_PROXY` and the
OS store), which suits most scripts. For two networks in one process, give a client its own
settings: every client is built on an `ApiClient`, which takes them.

```python
from libre_devops_helpers.core import ApiClient, CachingTokenProvider, token_source
from libre_devops_helpers.core.network import NetworkSettings
from libre_devops_helpers.microsoft import credential_for, load_config
from libre_devops_helpers.microsoft.entra import EntraClient

profile = load_config().get("prod-tenant")
tokens = CachingTokenProvider(credential_for(profile))
graph = profile.cloud.graph_url
lab = NetworkSettings(proxy="http://127.0.0.1:3128", no_proxy=(".lab.example",))
entra = EntraClient(
    ApiClient(graph, token_source(tokens, graph, profile.tenant_id), network_settings=lab)
)
```

The sign-in itself (the token requests) still follows the process's settings.

## Stability

The version is below 1.0: names in the library may still change between minor versions.
Each change a caller would notice is in the [changelog](../CHANGELOG.md), under the version
that made it.
