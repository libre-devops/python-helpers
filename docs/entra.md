# Entra ID and Intune

[Back to the docs](README.md)

## Devices and their groups

```bash
ldo entra devices web01,web02                   # in Entra? OS, trust type, last sign-in
ldo entra devices -f plan.xlsx --column FQDN --group "MDE Pilot Devices"
ldo entra devices web01 --group 55555555-5555-5555-5555-555555555555 --direct
ldo entra device-groups web01.corp.example.com  # every group one device is in
ldo entra group-devices "MDE Pilot Devices"     # every device in one group
```

`entra devices --group` checks each device is in the group, adding a column per group, and
exits 3 when a device is missing from Entra or from a group. A group is named by its object id
or its display name (a name two groups share is refused, with their ids); each group's members
are fetched once, however long the list. To check Defender onboarding at the same time, use
[`devices check --group`](devices.md#check-and-watch).

## Users, roles and apps

```bash
ldo entra group-members "Platform Admins" --kind user
ldo entra user-groups ana@example.com --direct
ldo entra user-roles ana@example.com            # active roles, and PIM-eligible ones
ldo entra sign-ins --user ana@example.com --since 7d --failures
ldo entra app-credentials --expiring 30d --service-principals
ldo entra ca-policies --state report-only
ldo intune devices laptop-042 laptop-043        # compliance, last sync, owner
```

Group commands include nested members unless you pass `--direct`. `app-credentials` exits 3
when a secret or certificate is close to expiry, so it can run on a schedule.

## Tokens

```bash
ldo entra token graph -p prod-tenant            # get a token and check what it covers
ldo entra token arm --raw                       # print it, for curl or a script
pbpaste | ldo entra inspect-token -             # check a token you already have
ldo entra sign-out -p pim                       # forget a kept sign-in
```

What the checks mean is in [Permissions](permissions.md#checking-a-token).
