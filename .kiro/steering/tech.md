---
inclusion: always
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# Working here

- Run everything through `just` (or `uv run`): `just check` before calling anything done
  (ruff, the format check, strict mypy, and the tests with coverage), `just ci` for all of
  CI's checks, `just fmt` to format, `just run <args>` to try the CLI.
- Python 3.11 or later: nothing newer than 3.11 in the code (`just test-311` proves it).
- ruff, line length 100. Match the surrounding code's naming, comment density and idiom.
- Runtime dependencies are `requests` and `typer` only. Everything else is the standard
  library. Do not add a runtime dependency without asking; test-only ones go in the `dev`
  group.
