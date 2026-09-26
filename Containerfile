# The ldo command line tool as a container image, built with podman (or docker).
#
#   podman build -t ldo .                      the tool and the Azure CLI (target "az", the
#                                              default), for signing in as yourself
#   podman build -t ldo:slim --target tool .   the tool alone
#
# Base images are pinned by digest and Dependabot keeps the digests fresh. Each build
# also applies the latest Debian security updates, so a scheduled rebuild (see
# .github/workflows/container.yml) patches the published images between releases.
#
# Behind a package proxy, where public images can be pulled but packages only come
# through an index such as JFrog's:
#
#   podman build --build-arg PACKAGE_INDEX=https://jfrog.example/api/pypi/pypi/simple \
#     --secret id=netrc,src=$HOME/.netrc \
#     --secret id=ca-bundle,src=/etc/ssl/certs/ca-certificates.crt \
#     --build-arg DEBIAN_UPGRADE=false .
#
# The versions and hashes are uv.lock's whichever index serves them. The index's login,
# when it needs one, is a build secret: mounted for the steps that install, never written
# into a layer or the image's history, as a build argument would be. So is the certificate
# bundle for an index behind an organisation's own authority: not secret, but only for
# the build, and it replaces the public roots, so it holds those too.

ARG PACKAGE_INDEX=https://pypi.org/simple
ARG DEBIAN_UPGRADE=true

# uv, only to install the locked dependencies; it never reaches a final image.
FROM ghcr.io/astral-sh/uv:0.12.18@sha256:3adc3706091ce7c2fe595e669628caedd6d951551b92b258b7e7dbe06d9440bc AS uv

# Build: the tool and its locked dependencies, into a virtual environment at /opt/ldo.
FROM docker.io/library/python:3.14-slim-trixie@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never
ARG PACKAGE_INDEX
WORKDIR /src
# Dependencies first, so a change to the code alone reuses this layer: the locked
# versions by name, from PACKAGE_INDEX, each checked against the hash uv.lock holds.
# --no-deps: they are the whole locked set, so nothing is resolved again (which would
# undo an override the lock applies, such as the Azure CLI's in container/azure-cli).
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=netrc,target=/root/.netrc \
    --mount=type=secret,id=ca-bundle,target=/run/secrets/ca-bundle \
    if [ -s /run/secrets/ca-bundle ]; then export SSL_CERT_FILE=/run/secrets/ca-bundle; fi \
    && uv export --frozen --no-dev --no-emit-project --format requirements-txt \
        --output-file /tmp/requirements.txt --quiet \
    && uv venv --quiet /opt/ldo \
    && uv pip install --quiet --python /opt/ldo/bin/python --default-index "$PACKAGE_INDEX" \
        --no-deps --require-hashes --requirement /tmp/requirements.txt
COPY README.md LICENSE ./
COPY src ./src
RUN --mount=type=secret,id=netrc,target=/root/.netrc \
    --mount=type=secret,id=ca-bundle,target=/run/secrets/ca-bundle \
    if [ -s /run/secrets/ca-bundle ]; then export SSL_CERT_FILE=/run/secrets/ca-bundle; fi \
    && uv pip install --quiet --python /opt/ldo/bin/python --default-index "$PACKAGE_INDEX" \
        --no-deps /src

# Build the Azure CLI, locked in container/azure-cli, into its own environment at /opt/az.
# Its bytecode is compiled in the next stage instead: the Azure CLI is over 12,000 files,
# and compiling them under emulation, for another architecture's image, takes longer
# than a build may run.
FROM build AS build-az
ARG PACKAGE_INDEX
COPY container/azure-cli/pyproject.toml container/azure-cli/uv.lock /src/azure-cli/
RUN --mount=type=secret,id=netrc,target=/root/.netrc \
    --mount=type=secret,id=ca-bundle,target=/run/secrets/ca-bundle \
    if [ -s /run/secrets/ca-bundle ]; then export SSL_CERT_FILE=/run/secrets/ca-bundle; fi \
    && uv export --frozen --no-dev --no-emit-project --project /src/azure-cli \
        --format requirements-txt --output-file /tmp/azure-cli.txt --quiet \
    && uv venv --quiet /opt/az \
    && UV_COMPILE_BYTECODE=0 uv pip install --quiet --python /opt/az/bin/python \
        --default-index "$PACKAGE_INDEX" --no-deps --require-hashes \
        --requirement /tmp/azure-cli.txt

# The Azure CLI's bytecode, compiled on the build machine's own platform. Bytecode is the
# same on every architecture for one Python version, and this is the same base image, so
# the result is what compiling in place would give, in seconds rather than an hour.
# unchecked-hash: the image never changes, so Python need not check the sources.
FROM --platform=$BUILDPLATFORM docker.io/library/python:3.14-slim-trixie@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2 AS compile-az
COPY --from=build-az /opt/az /opt/az
RUN python -W ignore -m compileall -q -j 0 --invalidation-mode unchecked-hash /opt/az/lib

# Runtime: the same base, patched, with a non-root user and the tool on PATH.
FROM docker.io/library/python:3.14-slim-trixie@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2 AS runtime
# DEBIAN_UPGRADE=false where Debian's mirrors cannot be reached: the base image's own
# packages are then the image's.
ARG DEBIAN_UPGRADE
RUN if [ "$DEBIAN_UPGRADE" = true ]; then \
        apt-get update \
        && apt-get upgrade --yes --no-install-recommends \
        && rm -rf /var/lib/apt/lists/*; \
    fi \
    && python -m pip uninstall --yes --root-user-action=ignore pip \
    && groupadd --gid 10001 ldo \
    && useradd --uid 10001 --gid ldo --home-dir /home/ldo --create-home \
        --shell /usr/sbin/nologin ldo \
    && install --directory --owner=ldo --group=ldo /work
COPY --from=build /opt/ldo /opt/ldo
ENV PATH=/opt/ldo/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.title="Libre DevOps Helpers" \
      org.opencontainers.image.description="The ldo command line tool: fast, read-only helpers for Entra ID, Defender XDR, Intune, Azure, Graph, PIM, Logic Apps and ServiceNow." \
      org.opencontainers.image.source="https://github.com/libre-devops/python-helpers" \
      org.opencontainers.image.url="https://github.com/libre-devops/python-helpers" \
      org.opencontainers.image.documentation="https://github.com/libre-devops/python-helpers#readme" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="docker.io/library/python:3.14-slim-trixie"
USER ldo:ldo
WORKDIR /work
ENTRYPOINT ["ldo"]
CMD ["--help"]

# The tool alone ("slim"), for device-code profiles and automation that need no Azure CLI.
FROM runtime AS tool

# The default target: the tool with the Azure CLI, for signing in as yourself (the
# default "azure-cli" profiles) and 'ldo az'.
FROM runtime AS az
COPY --from=compile-az /opt/az /opt/az
USER root
# A wrapper rather than a link, so az always runs on its own environment's Python.
RUN printf '#!/bin/sh\nexec /opt/az/bin/python -m azure.cli "$@"\n' > /usr/local/bin/az \
    && chmod 0755 /usr/local/bin/az \
    && install --directory --mode=0700 --owner=ldo --group=ldo /home/ldo/.azure
USER ldo:ldo
# The Azure CLI keeps its sign-in in ~/.azure: mount a volume there to keep it. The
# directory exists in the image so a new volume takes its owner. No telemetry, and no
# installing extensions on the fly (there is no pip to do it).
ENV AZURE_CORE_COLLECT_TELEMETRY=false \
    AZURE_EXTENSION_USE_DYNAMIC_INSTALL=no
LABEL org.opencontainers.image.title="Libre DevOps Helpers with the Azure CLI"
