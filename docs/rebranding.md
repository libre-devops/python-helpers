# Rebranding

[Back to the docs](README.md)

To run this inside a company under the company's own name, rename it with one command:

```bash
just rebrand --command contoso --display-name "Contoso Helpers" --dry-run   # preview
just rebrand --command contoso --display-name "Contoso Helpers" \
  --package contoso_helpers --repository https://git.contoso.example/platform/contoso-helpers \
  --banner contoso-logo.txt                                                   # or --no-banner
```

| Parameter | Renames | When not given |
| --- | --- | --- |
| `--command` | the command, and the config directory (`~/.config/<command>`) | unchanged |
| `--display-name` | the name in the banner, help and docs | unchanged |
| `--package` | the Python import name | unchanged |
| `--distribution` | the name you install | from `--package` |
| `--env-prefix` | every environment variable (`<PREFIX>_CONFIG`, ...) | from `--command` |
| `--error-class` | the base exception | from `--command`, e.g. `ContosoError` |
| `--repository` | every link to the repository | unchanged |
| `--banner`, `--no-banner` | the welcome art (plain ASCII) | unchanged |

The current names live in `brand.toml`, so the rename can run again later, and the running
tool takes its names from one module (`core/brand.py`). The recipe then relocks and runs every
check. `LICENSE` is never changed, since the MIT licence requires its notice to stay with the
code. A test rebrands a copy of the repository and runs the copy's whole suite, so the rename
keeps working as the code grows.

Replace the README's logo, badges and footer by hand: they point at Libre DevOps and this
repository's GitHub pages.
