# Defender XDR

[Back to the docs](README.md)

## Machines, alerts and vulnerabilities

```bash
ldo xdr machines web01 web02 --all-records      # onboarding, health, last seen, tags, device group
ldo xdr stale --older-than 30d                  # machines Defender has not seen lately
ldo xdr alerts --since 24h --severity medium
ldo xdr alerts --device web01 --include-resolved
ldo xdr vulns web01 --severity high
ldo xdr indicators                              # custom indicators of compromise
```

## Hunting

```bash
ldo xdr hunt "DeviceInfo | take 10"
ldo xdr hunt "EmailEvents | where Timestamp > ago(1d) | take 50" --timespan 7d
ldo xdr hunt --file queries/failed-logons.kql -o csv > failed-logons.csv
ldo xdr hunt "DeviceInfo | take 10" --endpoint  # the device tables, with the Azure CLI's sign-in
```

`xdr hunt` (and `graph hunt`, the same thing) runs through Microsoft Graph, which covers every
Defender XDR table: devices, email, identity, cloud apps and alerts. It needs
`ThreatHunting.Read.All`, which the Azure CLI's token never has: use a profile with
[your own app registration](authentication.md#your-own-app-registration). `--endpoint` uses the
Defender for Endpoint API instead: device tables only, but your Defender role is enough.

## Incidents, Sentinel's included

In the unified security operations platform, Sentinel's incidents land in the same queue as
Defender's, so these read both:

```bash
ldo xdr incidents top                           # today's open incidents, most severe first
ldo xdr incidents top --severity high -n 20
ldo xdr incidents latest --source sentinel      # the newest, any status, last 30 days
ldo xdr incidents list --from 2026-09-01 --to 2026-09-24
ldo xdr incidents list --yesterday --status resolved
ldo xdr incidents list --since 6h --updated     # updated, not created, in the last 6 hours
ldo xdr incidents summary --since 7d            # counts by severity, status and source
ldo xdr incidents show 12345                    # alerts, devices, users and the portal link
```

| Option | Values |
| --- | --- |
| window | `--today`, `--yesterday`, `--since 7d`, or `--from` and `--to` (whole local days: `YYYY-MM-DD`, `today`, `yesterday`); `--updated` windows on the last update |
| `--status` | `open`, `active`, `in-progress`, `awaiting-action`, `resolved`, `redirected`, `all` (repeatable) |
| `--severity` | at least `informational`, `low`, `medium` or `high` |
| `--source` | `sentinel`, `endpoint`, `identity`, `office`, `cloud-apps`, `cloud`, `xdr`, `entra`, `app-governance`, `dlp`, `insider-risk` (repeatable) |
| `-n`, `--limit` | how many |

Incidents need `SecurityIncident.Read.All` (the Azure CLI's token never has it) and a role
such as Security Reader. A Sentinel workspace not onboarded to the Defender portal keeps its
incidents to itself: read its `SecurityIncident` table with `ldo logs query`.
