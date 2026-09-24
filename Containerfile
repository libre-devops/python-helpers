# The ldo command line tool as a container image, built with podman (or docker).
#
#   podman build -t ldo .                      the tool and the Azure CLI (target "az", the
#                                              default), for signing in as yourself
#   podman build -t ldo:slim --target tool .   the tool alone
#
# Base images are pinned by digest and Dependabot keeps the digests fresh. Each build
# also applies the latest Debian security updates, so a scheduled rebuild (see
# .github/workflows/container.yml) patches the published images between releases.

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
WORKDIR /src
# Dependencies first, so a change to the code alone reuses this layer.
COPY pyproject.toml uv.lock ./
RUN UV_PROJECT_ENVIRONMENT=/opt/ldo uv sync --locked --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src ./src
RUN UV_PROJECT_ENVIRONMENT=/opt/ldo uv sync --locked --no-dev --no-editable

# Build the Azure CLI, locked in container/azure-cli, into its own environment at /opt/az.
FROM build AS build-az
COPY container/azure-cli/pyproject.toml container/azure-cli/uv.lock /src/azure-cli/
RUN UV_PROJECT_ENVIRONMENT=/opt/az uv sync --locked --no-dev --project /src/azure-cli

# Runtime: the same base, patched, with a non-root user and the tool on PATH.
FROM docker.io/library/python:3.14-slim-trixie@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2 AS runtime
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
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
      org.opencontainers.image.description="The ldo command line tool: read-only helpers for Azure, Entra ID, Defender for Endpoint, Intune, PIM, Key Vault and Log Analytics." \
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
COPY --from=build-az /opt/az /opt/az
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
