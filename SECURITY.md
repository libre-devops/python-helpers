# Security Policy

## Supported Versions

Only the latest release, and `main`, receive security updates. There is no backport
process: fixes land on `main` and go out in the next release.

## Scope

libre-devops-helpers (the `ldo` command) is a command line tool and
Python library that runs on your own machine or in your CI. It gets access tokens from the
Azure CLI, an app registration or a managed identity, and makes read-only calls to Microsoft
Graph, Defender for Endpoint, Azure Resource Manager, Key Vault (metadata only) and Log
Analytics. There is no server, no hosted service and no telemetry.

In scope:

- Token handling: any path by which an access token could be printed without `--raw`,
  written to disk, logged, or sent to a host other than the configured API.
- Credential handling in `src/libre_devops_helpers/microsoft/auth/`: any way for a
  client secret or federated token to be logged, shown in a repr or error, or sent anywhere
  but the Entra token endpoint; and the plain http allowed only for managed identity
  endpoints on loopback and link-local addresses.
- Key Vault access: any way for the tool to read a secret value, or to send a token to a
  host outside the cloud's Key Vault domain.
- Delegated sign-in (`microsoft/auth/delegated.py`): the browser flow's PKCE and `state`
  checks, the one-shot listener on 127.0.0.1, and any way for a token or refresh token to
  be logged, for an access token to outlive the command, or for a refresh token to be
  kept anywhere but the profile's `token_cache` (a private file unless it says
  otherwise).
- Kept sign-ins (`core/token_store.py`, `core/dpapi.py`): any way for a `file` cache to be
  created readable by other accounts or used while it is, for a `keychain` cache to be
  stored unencrypted, for an access token (rather than the refresh token) to be kept, or
  for one profile's kept sign-in to be used for another cloud, app or tenant. A `file`
  cache being readable by the account that owns it, or by root, is the documented trade of
  that option (and of the default), not a vulnerability.
- PIM: any way for a `pim` command to change an assignment or approve a request. They are
  meant to read only.
- Graph (`microsoft/graph`, `ldo graph`): any way for `graph get` to send the token to a
  host other than the profile's Graph endpoint, to make a request other than a GET (the
  one exception, `runHuntingQuery`, only runs a query), or for a path to reach outside
  Graph.
- Logic Apps (`microsoft/logicapps`): any way for a `logicapp` command to create or change
  a workflow in Azure (`validate` posts to the provider's validate endpoint, which creates
  nothing, and `export` only reads), or for a definition's file content to escape into a
  request path.
- ServiceNow sign-in (`servicenow/auth.py`): any way for a password, client secret or
  token to be logged, printed without `--raw`, written to the config file, or sent to a
  host other than the profile's instance; for the browser sign-in to accept an address
  from another sign-in (its `state` and PKCE checks); and for a kept sign-in to be used
  for another instance, application or profile. The `snow` commands only read.
- Signing in again (`cli/runtime.py`, `microsoft/auth/azure_cli.py`): any way for the offer
  to sign the Azure CLI back in to run without a person at a terminal saying yes, to sign
  in to a tenant other than the one whose sign-in lapsed, or to leave a different active
  account behind than the one before.
- The HTTP client in `src/libre_devops_helpers/core/http.py`, including its
  host pinning for `@odata.nextLink`, redirect handling and TLS verification.
- How external tools are run (`src/libre_devops_helpers/core/process.py`, and
  `microsoft/process.py` for the Azure CLI), including any way for input to reach a shell or
  change the arguments passed to a tool.
- Config file handling: parsing, validation, and the permissions the file is created with.
- Input files (`src/libre_devops_helpers/core/inputs.py` and `core/sheets.py`): any way for a
  text file, CSV or Excel workbook to run code, read files it should not, exhaust memory
  past the per-part size cap, or reach the XML parser with a document type declaration.
- The container images and `Containerfile`: running as root, a secret or credential baked
  into a layer, or a published image that skipped the vulnerability gate.
- Filter and path construction, where a device, user, group or vault name could alter an
  OData filter, an ARM path or the host a request goes to.
- The workflows in `.github/workflows/`, including their permissions, the checksum-pinned
  gitleaks and Trivy downloads, and the jobs with write access: the release job, and the
  container job when it publishes (packages, attestations and scan results).
- Dependency issues that affect this tool and do not already have a public advisory.

Out of scope:

- The token checks not verifying signatures. This is documented behaviour: they answer "is
  this the token I meant to get?", not "is this token genuine?".
- What your own account is allowed to read. The tool uses your permissions and cannot grant
  more.
- Vulnerabilities in the Azure CLI, Microsoft Graph or Defender for Endpoint themselves,
  including the Azure CLI's pinned dependencies in the default container image, which the scan reports
  in the Security tab when a fix exists.
  Report those to Microsoft through the
  [Microsoft Security Response Center](https://msrc.microsoft.com/report).
- Vulnerabilities in third-party dependencies that already carry a public advisory.
  Dependabot tracks those automatically, so a report adds nothing.

## Reporting a Vulnerability

Report privately using GitHub's private vulnerability reporting:

**https://github.com/libre-devops/python-helpers/security/advisories/new**

Do **not** open a public issue for an undisclosed vulnerability, and never include a real
access token, tenant id or host name in a report. Use placeholders.

Please include:

- The affected component and version or commit.
- Reproduction steps.
- The impact you believe it has.
- Any suggested remediation, if you have one.

## What to Expect

- Acknowledgement of receipt within **3 business days**.
- An initial triage decision within **7 business days**.

If the report is accepted, we will develop a fix and coordinate disclosure timing with you
once a patch is released. If it is declined, we will tell you why: for example, not
reproducible, out of scope as described above, or already publicly known.

Please hold off on public disclosure until remediation is complete. This is a
volunteer-maintained project, so please be reasonable about timelines.

Published advisories:
**https://github.com/libre-devops/python-helpers/security/advisories**
