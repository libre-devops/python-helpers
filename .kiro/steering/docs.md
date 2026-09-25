---
inclusion: fileMatch
fileMatchPattern: ["**/*.md"]
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# Docs

- `README.md` is a short front page: the command table, install, quickstart and links.
  Detail goes in `docs/`, one page per area. `CHANGELOG.md` gets an `Unreleased` entry for
  every change a user would notice.
- `tests/project/test_docs.py` runs every `ldo` example in the README, `docs/` and this file
  with `--help`, checks every `just` example is a recipe, and follows every link. Keep
  examples real.
- UK English (colour, organisation, licence as a noun). Never use em or en dashes, in any
  file: use commas, colons, brackets or a plain hyphen.
