# Microsoft Graph

[Back to the docs](README.md)

A fast way to read Graph with a profile's sign-in, like `az rest`, but knowing Graph.

```bash
ldo graph whoami                                 # who the token is for, its scopes, its expiry
ldo graph token --raw                            # a checked Graph token, for curl or a script
ldo graph get me
ldo graph get users --select id,displayName,userPrincipalName --all -o csv
ldo graph get users --filter "startswith(displayName,'Ana')" --count
ldo graph get users --search "displayName:ana"
ldo graph get devices --top 50 --limit 200
ldo graph get "https://graph.microsoft.com/beta/me/memberOf"   # pasted from Graph Explorer
ldo graph get security/alerts_v2 --beta
ldo graph get-user ana@example.com               # by UPN, id or display name
ldo graph get-device web01.corp.example.com      # FQDN, then short name
ldo graph get-group "MDE Pilot Devices"
ldo graph get-app billing-api                    # by name, object id or app id
ldo graph get-sp "Microsoft Graph"
ldo graph hunt "IdentityLogonEvents | take 10"   # the same as xdr hunt
```

- `get` takes a path (`users`, `/me/memberOf`, `beta/...`) or a full Graph URL, and shows one
  page unless you pass `--all` or `--limit`, saying when there are more.
- `--count` and `--search` send `ConsistencyLevel: eventual` for you; `--eventual` sends it
  for other advanced queries. `--search` is quoted for you.
- Collections come back as rows (the familiar columns, or those you `--select`), objects as
  their fields, and `-o json` gives Graph's records whole.
- Everything reads: there is no POST, PATCH or DELETE. The token only ever goes to the
  profile's Graph host.

What a call may read depends on the token: `ldo graph whoami` lists its scopes. The Azure
CLI's token reads the directory, users, groups and devices; the security APIs need a profile
with [your own app registration](authentication.md#your-own-app-registration).
