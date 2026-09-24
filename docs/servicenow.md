# ServiceNow

[Back to the docs](README.md)

```bash
ldo snow sign-in                  # sign in once; the sign-in is kept
ldo snow whoami                   # who you are, your roles, which features they cover
ldo snow instance                 # the release, and whether Security Incident Response is there
ldo snow apps security --all      # applications (store and custom), active or not
ldo snow token --raw              # an access token, for curl or a script
ldo snow sign-out                 # forget the kept sign-in
```

## Signing in

Sign-in is OAuth, through an application registry entry on the instance. You sign in once and
the refresh token is kept (as for Microsoft; see [Keeping a sign-in](authentication.md#keeping-a-sign-in)),
so later commands sign in by themselves until it lapses, 100 days by default.

| `sign_in` | How |
| --- | --- |
| `browser` (the default) | `ldo` shows a link. Open it in any browser, sign in as usual (single sign-on and MFA work), then paste back the `http://localhost:8765/callback?code=...` address the browser lands on; the page not loading is expected. Works headless, and where passwords are not allowed on the API. |
| `password` | your username and password, once, from `SNOW_INSTANCE_PASSWORD` or asked for. For a developer instance, or an account with a local password. |

The client secret comes from `SNOW_CLIENT_SECRET`, or `sign-in` asks for it (hidden) and keeps
it with the sign-in. There is no option to pass it on the command line, where it would land in
your shell history.

`auth = "basic"` sends the password with every request instead. ServiceNow refuses that for
interactive accounts unless they hold the `snc_basic_auth_api_access` role, so prefer OAuth.

## Configuration

The environment is enough:

```bash
export SNOW_INSTANCE_URL=https://dev12345.service-now.com
export SNOW_CLIENT_ID=<client id>
ldo snow sign-in
```

or one profile per instance in the config file:

```toml
[servicenow]
default_profile = "work"

[servicenow.profiles.work]
instance = "https://yourcompany.service-now.com"
client_id = "<client id>"

[servicenow.profiles.dev]
instance = "dev12345"          # short for https://dev12345.service-now.com
client_id = "<client id>"
sign_in = "password"
username = "admin"
```

## The application registry entry

An admin on the instance makes it once, and everyone signs in through it:

1. All > System OAuth > Application Registry > New > **Create an OAuth API endpoint for
   external clients**.
2. **Name**: anything, e.g. `ldo`. Leave **Client Secret** empty to have one generated, then
   reopen the record to copy the Client ID and Secret.
3. **Redirect URL**: `http://localhost:8765/callback`, exactly (or a profile's
   `redirect_uri`).
4. **Refresh Token Lifespan**: how long a sign-in lasts; the default 100 days is fine.
   Leave **Access Token Lifespan** at its default.
5. **Active** ticked, **Public Client** unticked.

A token can do what your account can, no more.

## Security Incident Response on a developer instance

A personal developer instance does not have it until you add it: on developer.servicenow.com,
open your instance's menu, choose **Activate Plugin**, and find Security Incident Response
(or, as admin on the instance, All > System Applications > All Available Applications). Then
`ldo snow instance` shows it installed.
