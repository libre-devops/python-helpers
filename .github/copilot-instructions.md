# Instructions for GitHub Copilot

This repository's instructions for AI coding assistants are in [`AI.md`](../AI.md) at the
root (and, word for word, in `AGENTS.md`, which the Copilot coding agent also reads). Read
`AI.md` before suggesting or making any change here.

The rules that matter most:

- Every command reads; nothing changes a tenant or an instance unless asked.
- Runtime dependencies are `requests` and `typer` only; the rest is the standard library.
- Tests never touch the network: use the fakes in `tests/fakes`. Run `just check`.
- Never hard-code `ldo` or `LDO_`: take names from `core/brand.py`.
- UK English, and no em or en dashes anywhere.
- No AI attribution in commits, and nothing is committed until the person asks.
