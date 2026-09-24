# Using it as a library

[Back to the docs](README.md)

The code is layered by vendor, and a test enforces the layering:

| Package | Depends on | Holds |
| --- | --- | --- |
| `core` | nothing | errors, config, the brand, the token cache, the HTTP client (retries, Retry-After, paging), polling, input parsing, query results, logging |
| `microsoft` | `core` | clouds, APIs as tokens see them, token checks, credentials, the Azure CLI runner, `[microsoft]` profiles |
| `microsoft.azcli` | `core`, `microsoft` | Azure CLI accounts, sign-in and profile switching |
| `microsoft.entra` | `core`, `microsoft` | devices, users, groups, roles, sign-ins, app credentials, Conditional Access |
| `microsoft.xdr` | `core`, `microsoft` | Defender machines, alerts, vulnerabilities, indicators, hunting (the endpoint API) |
| `microsoft.graph` | `core`, `microsoft` | any Graph GET with paging, objects by name or id, hunting over the whole XDR schema |
| `microsoft.incidents` | `core`, `microsoft` | Defender XDR incidents, Sentinel's included |
| `microsoft.intune` | `core`, `microsoft` | managed devices and compliance |
| `microsoft.azure` | `core`, `microsoft` | subscriptions, Resource Graph, RBAC, Defender for Cloud |
| `microsoft.keyvault`, `microsoft.loganalytics` | `core`, `microsoft` | secret, certificate and key metadata; KQL against a workspace |
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
