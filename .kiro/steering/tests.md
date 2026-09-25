---
inclusion: fileMatch
fileMatchPattern: ["tests/**"]
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# Tests

- Tests mirror `src` (`tests/core`, `tests/microsoft/<feature>`, `tests/cli/commands`), one
  test module per module, and `tests/project/test_layout.py` checks it.
- Nothing touches the network, a real `az` or a real clock. HTTP goes through
  `tests/fakes/http.py` (`routes`, `fake_session`), `az` through `fakes/azcli.py`, time
  through `fakes/clock.py`. Shared fakes live in `tests/fakes`, one module per concern.
- Coverage is gated at 93% (`fail_under` in `pyproject.toml`). Keep new code covered.
- CI runs with `GITHUB_ACTIONS` set, which makes Typer colour and wrap errors: compare error
  text with `usage_error(result)`, never a raw substring of `result.output`.
- Windows caps an environment variable at 32,767 characters and pytest puts each test id in
  one: give big parametrised values short `ids`.
- `tests/project/test_rebrand.py` renames a copy of the repository and runs its whole suite.
