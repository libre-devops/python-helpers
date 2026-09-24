# libre-devops-helpers task runner. Run `just` to list the recipes.
# Everything goes through uv, so `just sync` is the only setup step.

set shell := ["bash", "-euo", "pipefail", "-c"]
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# List the recipes
default:
    @just --list

# Install runtime and dev dependencies into .venv
sync:
    uv sync

# Lint with ruff
lint:
    uv run ruff check src tests scripts

# Check formatting without changing files
fmt-check:
    uv run ruff format --check src tests scripts

# Apply formatting and safe lint fixes
fmt:
    uv run ruff format src tests scripts
    uv run ruff check --fix src tests scripts

# Run the unit tests (no network, no real az); extra args go to pytest
test *args:
    uv run pytest {{ args }}

# Everything a pull request must pass
check: lint fmt-check test

# Run the CLI, e.g. just run whoami
run *args:
    uv run ldo {{ args }}

# Put ldo on PATH as an editable uv tool
install:
    uv tool install --editable . --force

# Create the config file from the template
config-init:
    uv run ldo config init

# Switch the Azure CLI to a profile, e.g. just use test-tenant
use profile:
    uv run ldo use {{ quote(profile) }}

# Check devices across Entra and Defender, e.g. just check-devices "web01,web02" --tag linux
check-devices devices *args:
    uv run ldo devices check {{ quote(devices) }} {{ args }}

# Watch devices until they are all complete, e.g. just watch-devices "web01,web02" --timeout 2h
watch-devices devices *args:
    uv run ldo devices watch {{ quote(devices) }} {{ args }}

# Test on the oldest supported Python as well as the default one
test-311 *args:
    uv run --python 3.11 --isolated --with pytest --with-editable . pytest {{ args }}

# Get and check a token, e.g. just token mde -p prod-tenant
token resource="graph" *args:
    uv run ldo token {{ quote(resource) }} {{ args }}

# Rename the project for another organisation; every name is a parameter, e.g.
#   just rebrand --command contoso --display-name "Contoso Helpers" --dry-run
# Run 'just rebrand --help' for them all. Without --dry-run it rewrites, relocks and checks.
[unix]
[positional-arguments]
rebrand *args:
    uv run --no-sync python scripts/rebrand.py "$@"

# On Windows, quote multi-word values with single quotes, e.g. --display-name 'Contoso Helpers'
[windows]
rebrand *args:
    uv run --no-sync python scripts/rebrand.py {{ args }}
