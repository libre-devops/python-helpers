# Container images

[Back to the docs](README.md)

Each release is published to GitHub Container Registry for `linux/amd64` and `linux/arm64`:

| Image | Inside | For |
| --- | --- | --- |
| `ghcr.io/libre-devops/python-helpers:latest` | `ldo` and the Azure CLI | signing in as yourself |
| `ghcr.io/libre-devops/python-helpers:slim` | `ldo` alone | `device-code` profiles, and automation |

Both are built on `python:3.14-slim` (Debian 13), pinned by digest, and run as an
unprivileged user (uid 10001) in `/work`. The Azure CLI has a virtual environment of its own,
locked in `container/azure-cli`, and no pip, so `az extension add` does not work there.

| Tag (`-slim` for slim) | Moves? | Meaning |
| --- | --- | --- |
| `0.6.0` | to patched rebuilds | that release |
| `0.6` | yes | the newest 0.6.x |
| `latest`, `slim` | yes | the newest release |
| `0.6.0-20260928.57` | never | one build: its date and workflow run |

Pin a stamped tag or a digest for a build that never changes, or `0.6` to take patches as
they land. Each image carries a build provenance attestation and an SBOM:

```bash
gh attestation verify oci://ghcr.io/libre-devops/python-helpers:latest --owner libre-devops
```

Each release is also in the GitLab copy's registry, for `linux/amd64`, with the same tags
but for the weekly patched rebuilds (see [GitLab CI](development.md#gitlab-ci)):
`registry.gitlab.com/libre-devops/python-helpers:latest`.

## Running it

Give the Azure CLI's state a named volume, so you sign in once and later containers reuse
it, without sharing your own `~/.azure`. With rootless podman, map your user to the image's:

```bash
podman volume create ldo-azure
alias ldo='podman run --rm -it --userns=keep-id:uid=10001,gid=10001 \
  -v ldo-azure:/home/ldo/.azure \
  -v ~/.config/ldo:/home/ldo/.config/ldo:ro,z \
  -v "$PWD":/work:ro,z \
  ghcr.io/libre-devops/python-helpers:latest'

ldo az use prod-tenant --device-code      # sign in once; there is no browser in a container
ldo devices check -f plan.xlsx --column FQDN
```

With docker, use `--user "$(id -u):$(id -g)"` in place of `--userns`. The `z` option relabels
mounts for SELinux and does nothing elsewhere.

Behind a corporate proxy, pass it in with `-e LDO_PROXY_ADDRESS=...` (a cntlm on the host is
at `host.containers.internal`); see [Proxies and certificates](network.md#in-a-container).

`slim` has no Azure CLI. Use it with a `device-code` profile (and a volume at
`/home/ldo/.local/state/ldo` to keep the sign-in), or for automation with a
`workload-identity` profile and the job's federated token passed through.

## Building it

```bash
just image                 # the default image, as localhost/ldo:dev
just image-slim            # the slim image, as localhost/ldo:dev-slim
just image-run az whoami   # run it, with this directory, your config and the ldo-azure volume
just image-scan slim       # the vulnerability scan CI runs (needs trivy)
```

`podman build .` and `docker build -f Containerfile .` work too. How the images are kept
patched is in [Development](development.md#patching).

### Behind a package proxy

Where public base images can be pulled but packages only come through an index, such as a
company's JFrog in front of PyPI, point the build at the index and give it the index's
login, and the certificate bundle that trusts it, as build secrets:

```bash
podman build \
  --build-arg PACKAGE_INDEX=https://jfrog.example/artifactory/api/pypi/pypi/simple \
  --secret id=netrc,src=$HOME/.netrc \
  --secret id=ca-bundle,src=/etc/ssl/certs/ca-certificates.crt \
  --build-arg DEBIAN_UPGRADE=false \
  .
```

| Build argument or secret | For | Default |
| --- | --- | --- |
| `PACKAGE_INDEX` | the index every Python package comes from | `https://pypi.org/simple` |
| `netrc` (a secret) | a netrc file with the index's login (`machine HOST login USER password TOKEN`) | none: the index is read anonymously |
| `ca-bundle` (a secret) | a PEM bundle for an index behind your organisation's own certificate authority. It replaces the public roots, so give the whole bundle, such as your machine's | the public roots |
| `DEBIAN_UPGRADE` | `false` to leave out the Debian security updates, where Debian's mirrors cannot be reached | `true` |

The packages are the versions `uv.lock` pins, each checked against the hash it holds,
whichever index serves them. The login and the bundle are mounted only for the steps that
install, and are never written into a layer or the image's history, as a build argument
would be. Without the Debian updates the image has the base image's own packages, so keep
the base image's digest current.

## Why the Azure CLI is not a Python dependency

`azure-cli` is on PyPI, but it brings about 150 packages and 350 MB, many pinned exactly, and
anything importing this package would inherit those pins. `ldo` needs none of it: it calls
the REST APIs with `requests`, and its own credentials cover secrets, workload and managed
identity, and browser or device code sign-in. The Azure CLI is only there for the default
sign-in, which reuses the session you already have, so it stays an outside program: on your
`PATH`, or inside the default image.
