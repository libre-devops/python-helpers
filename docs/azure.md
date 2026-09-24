# Azure, Key Vault and Log Analytics

[Back to the docs](README.md)

## Azure

```bash
ldo azure subscriptions
ldo azure resource-graph "resources | summarize count() by type | order by count_ desc"
ldo azure rbac ana@example.com                  # every role assignment that applies
ldo azure secure-score --controls
ldo azure recommendations --severity high
ldo azure defender-plans
```

Azure commands cover the profile's subscription when it pins one, otherwise every
subscription the credential can see in the tenant; `-s`/`--subscription` (repeatable)
chooses. `rbac` includes assignments made to the principal's groups and those inherited from
management groups.

## Key Vault

```bash
ldo keyvault expiry kv-app-prd kv-app-dev --within 60d
ldo keyvault expiry --all-vaults --kind certificate     # every vault, found through Resource Graph
```

Metadata only: it never reads a secret's value. Exits 3 when anything expires within the
window.

## Log Analytics

```bash
ldo logs query "Heartbeat | summarize arg_max(TimeGenerated, *) by Computer" --timespan 1d
ldo logs query --file queries/sign-ins.kql --workspace <workspace id> -o csv
```

Without `--workspace`, the profile's `workspace_id` is used. A Sentinel workspace is a Log
Analytics workspace, so this reads its tables too.
