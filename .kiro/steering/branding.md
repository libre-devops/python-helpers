---
inclusion: always
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# Names and branding

The project can be renamed (`just rebrand`). Never hard-code `ldo`, `LDO_` or the package
name in code: use `core/brand.py` (`brand.COMMAND`, `brand.env_var("X")`,
`brand.command("config init")`, `brand.docs("page")` for a link to a docs page).
