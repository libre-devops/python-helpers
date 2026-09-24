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

## Automation

```bash
ldo azure automation accounts
ldo azure automation jobs aa-ops                        # the newest 20 runs, and how each ended
ldo azure automation jobs aa-ops --runbook Rotate-Keys --since 7d
ldo azure automation jobs aa-ops --failed               # failed, suspended or stopped
ldo azure automation logs aa-ops                        # the newest run's logs, and why it failed
ldo azure automation logs aa-ops --runbook Rotate-Keys --stream error --full
ldo azure automation logs aa-ops 0b1c2d3e-aaaa-4bbb-8ccc-123456789abc
ldo azure automation output aa-ops --runbook Rotate-Keys > rotate-keys.txt
```

An account is named by its name, found across the subscriptions in scope (`-g` narrows it to
a resource group when names repeat), or by its resource id. Without a job id, `logs` and
`output` take the newest job, of `--runbook` when given. `logs` shows the job (its status,
who or what started it, and the exception when it failed) and then every record it wrote,
oldest first: output, warnings and errors, and verbose, progress and debug records when the
runbook turns them on. A listing carries each record's summary; `--full` reads each in full.
`jobs` and `logs` exit 3 when a job shown failed. Jobs are kept for 30 days, and Reader on the
account is enough to read them.

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
