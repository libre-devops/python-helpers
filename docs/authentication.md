# Signing in

[Back to the docs](README.md)

`ldo` works as you: it signs in with your own account and can read only what you can.

## As yourself

| `auth` | When | Needs |
| --- | --- | --- |
| `azure-cli` (the default) | almost always: it reuses the sign-in you already have | `az login` |
| `interactive` | commands whose scopes the Azure CLI's token never carries: PIM on Entra roles and groups, incidents, Graph hunting | `client_id` of [your own app](#your-own-app-registration); signs in in a browser |
| `device-code` | the same, over SSH, in WSL, in a container, anywhere without a browser | the same `client_id`; you enter a code at the device login page |

```bash
ldo az use prod-tenant       # switch the Azure CLI to a profile, signing in when needed
ldo az use prod-tenant --device-code
ldo az whoami                # the Azure CLI's active account, and the profile it matches
ldo entra sign-out -p pim    # forget an interactive or device-code profile's kept sign-in
```

Tokens are requested per tenant, so `az use` is optional: a profile for another tenant works
without switching. An `interactive` profile falls back to a device code when no browser can
be opened.

## Automation

Unattended jobs can run the same commands with an identity of their own:

| `auth` | For | Needs |
| --- | --- | --- |
| `client-secret` | a job with an app registration and a secret | `client_id`, and the secret in `AZURE_CLIENT_SECRET` |
| `workload-identity` | CI and Kubernetes, with no secret at all | `client_id`, and a federated token from `AZURE_FEDERATED_TOKEN_FILE` or GitHub Actions OIDC |
| `managed-identity` | code on an Azure host | nothing, or `client_id` for a user-assigned identity |

These never lapse: every token is a fresh exchange. In GitHub Actions, give the job
`id-token: write` and the app registration a federated credential for the workflow:

```yaml
permissions:
  id-token: write
  contents: read
steps:
  - run: uv tool install git+https://github.com/libre-devops/python-helpers@v0.4.1
  - run: ldo --config .github/ldo.toml entra app-credentials -p ci --expiring 30d
```

## When a sign-in lapses

Access tokens last about an hour and are renewed for you, five minutes before they expire,
so a two-hour `devices watch` carries on by itself. A 401 drops the cached token and retries
once. Your sign-in behind them lasts days or weeks, but Entra ID ends it in cases no code can
avoid:

| Cause | Entra ID code | Again? |
| --- | --- | --- |
| a sign-in frequency policy (every 8 hours, say) | AADSTS70043, AADSTS70044 | yes, on that schedule |
| unused for too long (90 days) | AADSTS700082 | only after a long gap |
| a password change or expiry | AADSTS50132, AADSTS50133, AADSTS50055 | no |
| revoked by an administrator, or "sign out everywhere" | AADSTS50173 | no |
| MFA newly required, expired, or not set up | AADSTS50076, AADSTS50078, AADSTS50079 | depends on the policy |

The error names the cause. On a terminal, `ldo` offers to sign the Azure CLI back in to that
tenant and carries on, then restores whichever account was active. `devices check` and
`watch` ask between passes and repeat the pass a lapse interrupted. Scripts and CI never see
the question. `LDO_REAUTH=device-code` uses a device code; `LDO_REAUTH=off` never asks.
`interactive` and `device-code` profiles sign in again by themselves, and say why.

After activating a role in PIM, the Azure CLI may hand out its old token (and old
permissions) for up to an hour; an `interactive` or `device-code` profile starts each command
with a new one.

## Keeping a sign-in

An `interactive` or `device-code` profile keeps its refresh token, so the next command signs
in without asking. Access tokens are never kept. `token_cache` on the profile says where:

| `token_cache` | Kept in | Use it on |
| --- | --- | --- |
| `file` (the default) | `~/.local/state/ldo/refresh-tokens.json` (`%LOCALAPPDATA%\ldo` on Windows), readable only by you | your own machines, headless or not |
| `keychain` | macOS Keychain, the Secret Service on Linux, or a DPAPI-encrypted file on Windows | a desktop where you want it locked away |
| `memory` | nowhere: gone when the command ends | shared machines and jump hosts |

A refresh token is as good as your sign-in to that app until it expires or is revoked. The
file is the trade the Azure CLI makes on Linux: fine on a machine that is yours. A cache file
other accounts can read is refused, as ssh refuses a readable key. `keychain` on macOS and
Linux needs the `keychain` extra:

```bash
uv tool install "libre-devops-helpers[keychain] @ git+https://github.com/libre-devops/python-helpers@v0.4.1"
```

## Your own app registration

The Azure CLI's token carries the scopes Microsoft chose, and the PIM, incident and hunting
scopes are not among them. Register a public client app once per tenant, grant it the
delegated read scopes, and have an administrator consent:

```bash
app=$(az ad app create --display-name "ldo (delegated sign-in)" \
  --public-client-redirect-uris http://localhost --is-fallback-public-client true \
  --query appId -o tsv)
graph=00000003-0000-0000-c000-000000000000       # Microsoft Graph
arm=797f4846-ba00-4fd7-ba43-dac1f8f63013         # Azure Service Management
for scope in Directory.Read.All RoleEligibilitySchedule.Read.Directory \
  RoleAssignmentSchedule.ReadWrite.Directory RoleManagementPolicy.Read.Directory \
  PrivilegedEligibilitySchedule.Read.AzureADGroup PrivilegedAssignmentSchedule.ReadWrite.AzureADGroup \
  RoleManagementPolicy.Read.AzureADGroup SecurityIncident.Read.All ThreatHunting.Read.All; do
  id=$(az ad sp show --id $graph --query "oauth2PermissionScopes[?value=='$scope'].id" -o tsv)
  az ad app permission add --id "$app" --api $graph --api-permissions "$id=Scope"
done
id=$(az ad sp show --id $arm --query "oauth2PermissionScopes[?value=='user_impersonation'].id" -o tsv)
az ad app permission add --id "$app" --api $arm --api-permissions "$id=Scope"
az ad app permission admin-consent --id "$app"
echo "client_id = \"$app\""
```

```toml
[microsoft.profiles.me]
tenant_id = "<tenant guid>"
auth = "interactive"            # or "device-code"
client_id = "<the app id printed above>"
```

Graph insists on a ReadWrite scope even to list PIM requests; `ldo` only ever reads.
