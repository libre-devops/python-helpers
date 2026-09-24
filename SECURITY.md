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
  outlive the command, reach disk, or be logged.
- PIM: any way for a `pim` command to change an assignment or approve a request. They are
  meant to read only.
- The HTTP client in `src/libre_devops_helpers/core/http.py`, including its
  host pinning for `@odata.nextLink`, redirect handling and TLS verification.
- How external tools are run (`src/libre_devops_helpers/core/process.py`, and
  `microsoft/process.py` for the Azure CLI), including any way for input to reach a shell or
  change the arguments passed to a tool.
- Config file handling: parsing, validation, and the permissions the file is created with.
- Filter and path construction, where a device, user, group or vault name could alter an
  OData filter, an ARM path or the host a request goes to.
- The workflows in `.github/workflows/`, including their permissions, the checksum-pinned
  gitleaks download, and the release job, the only one with write access.
- Dependency issues that affect this tool and do not already have a public advisory.

Out of scope:

- The token checks not verifying signatures. This is documented behaviour: they answer "is
  this the token I meant to get?", not "is this token genuine?".
- What your own account is allowed to read. The tool uses your permissions and cannot grant
  more.
- Vulnerabilities in the Azure CLI, Microsoft Graph or Defender for Endpoint themselves.
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
