# libre-devops-helpers task runner. Run `just` to list the recipes.
# Everything goes through uv, so `just sync` is the only setup step.

set shell := ["bash", "-euo", "pipefail", "-c"]
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# List the recipes
default:
    @just --list --unsorted

# Install runtime and dev dependencies into .venv
[group('setup')]
sync:
    uv sync

# Put ldo on PATH as an editable uv tool
[group('setup')]
install:
    uv tool install --editable . --force

# Relock the tool and the image's Azure CLI, e.g. after editing a pyproject.toml
[group('setup')]
lock:
    uv lock
    uv lock --project container/azure-cli

# Write AGENTS.md and Kiro's .kiro/steering/ from AI.md, the instructions every AI assistant reads
[group('setup')]
ai:
    uv run --no-sync python scripts/ai_instructions.py

# Run ldo from the working tree, e.g. just run devices check web01
[group('run')]
run *args:
    uv run ldo {{ args }}

# Lint with ruff
[group('check')]
lint:
    uv run ruff check src tests scripts

# Type-check the package, strictly (the settings are in pyproject.toml)
[group('check')]
typecheck:
    uv run mypy

# Check formatting without changing files
[group('check')]
fmt-check:
    uv run ruff format --check src tests scripts

# Apply formatting and safe lint fixes
[group('check')]
fmt:
    uv run ruff format src tests scripts
    uv run ruff check --fix src tests scripts

# Run the tests (no network, no real az); extra args go to pytest, e.g. just test -k devices
[group('check')]
test *args:
    uv run pytest {{ args }}

# Run the tests on the oldest supported Python
[group('check')]
test-311 *args:
    uv run --python 3.11 --isolated --with pytest --with pyyaml --with trustme --with jsonschema --with-editable . pytest {{ args }}

# Run the tests with line and branch coverage; fails below the floor in pyproject.toml
[group('check')]
coverage *args:
    uv run pytest --cov --cov-report=term-missing {{ args }}

# Lint, format check, type check and tests with coverage: what every change must pass
[group('check')]
check: lint fmt-check typecheck coverage

# Audit the locked dependencies for known vulnerabilities, as CI does
[group('check')]
[unix]
[script("bash")]
audit:
    set -euo pipefail
    requirements="$(mktemp)"
    trap 'rm -f "$requirements"' EXIT
    uv export --frozen --all-extras --format requirements-txt --no-emit-project --output-file "$requirements" > /dev/null
    uvx pip-audit --strict --disable-pip --require-hashes --requirement "$requirements"

# Scan the working tree for secrets, uncommitted changes included (needs gitleaks)
[group('check')]
secrets:
    gitleaks dir --config .gitleaks.toml --redact --no-banner .

# Build the sdist and wheel into dist/, and prove the wheel installs and runs
[group('check')]
[unix]
[script("bash")]
build:
    set -euo pipefail
    rm -rf dist
    uv build
    smoke="$(mktemp -d)"
    trap 'rm -rf "$smoke"' EXIT
    uv venv --quiet "$smoke"
    uv pip install --quiet --python "$smoke" dist/*.whl
    "$smoke/bin/ldo" --version

# Everything CI checks, apart from the secret scan (just secrets) and the images
[group('check')]
[unix]
ci: check test-311 audit build

# Build the default image (the tool and the Azure CLI) as localhost/ldo:dev
[group('image')]
[unix]
image *args:
    podman build --target az --tag localhost/ldo:dev {{ args }} .

# Build the slim image (the tool alone) as localhost/ldo:dev-slim
[group('image')]
[unix]
image-slim *args:
    podman build --target tool --tag localhost/ldo:dev-slim {{ args }} .

# The Azure CLI's sign-in is kept in the ldo-azure volume, never in your own ~/.azure.
[doc("Run ldo from the default image with this directory and your config, e.g. just image-run az whoami")]
[group('image')]
[unix]
[positional-arguments]
[script("bash")]
image-run *args:
    set -euo pipefail
    config="${XDG_CONFIG_HOME:-$HOME/.config}/ldo"
    flags=(--rm -i --userns=keep-id:uid=10001,gid=10001 -v "$PWD:/work:ro,z")
    flags+=(-v ldo-azure:/home/ldo/.azure)
    if [ -t 1 ]; then flags+=(-t); fi
    if [ -d "$config" ]; then flags+=(-v "$config:/home/ldo/.config/ldo:ro,z"); fi
    podman run "${flags[@]}" localhost/ldo:dev "$@"

# Scan a built image as CI does (needs trivy), e.g. just image-scan slim
[group('image')]
[unix]
[script("bash")]
image-scan variant="default":
    set -euo pipefail
    archive="$(mktemp --suffix=.tar)"
    trap 'rm -f "$archive"' EXIT
    podman save --quiet --output "$archive" "localhost/ldo:dev{{ if variant == "slim" { "-slim" } else { "" } }}"
    trivy image --input "$archive" --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed

# Tag this commit with the version in pyproject.toml and push the tag, which releases it
[group('release')]
[unix]
[confirm("Tag this commit with the version in pyproject.toml and push the tag?")]
[script("bash")]
release:
    set -euo pipefail
    version="$(uv run --no-sync python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
    fail() { echo "error: $1" >&2; exit 1; }
    [ -z "$(git status --porcelain)" ] || fail "the working tree has uncommitted changes"
    [ "$(git rev-parse --abbrev-ref HEAD)" = main ] || fail "releases are tagged on main"
    git fetch --quiet origin main
    [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || fail "main is not the same as origin/main"
    grep -qx "## ${version}" CHANGELOG.md || fail "CHANGELOG.md has no '## ${version}' section"
    if git rev-parse --quiet --verify "refs/tags/v${version}" > /dev/null; then fail "v${version} already exists"; fi
    git tag --annotate "v${version}" --message "${version}"
    git push origin "v${version}"
    echo "pushed v${version}: the release workflow builds, publishes and creates the release"

# Every name is a parameter; run 'just rebrand --help' for them all. Without --dry-run it
# rewrites, relocks and checks.
[doc('Rename the project for another organisation, e.g. just rebrand --command contoso --dry-run')]
[group('release')]
[unix]
[positional-arguments]
rebrand *args:
    uv run --no-sync python scripts/rebrand.py "$@"

# On Windows, quote multi-word values with single quotes, e.g. --display-name 'Contoso Helpers'
[doc('Rename the project for another organisation, e.g. just rebrand --command contoso --dry-run')]
[group('release')]
[windows]
rebrand *args:
    uv run --no-sync python scripts/rebrand.py {{ args }}
