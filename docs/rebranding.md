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
| `--banner-picture` | a picture drawn above it, in its own colours: a logo, say (see below) | none |

The current names live in `brand.toml`, so the rename can run again later, and the running
tool takes its names from one module (`core/brand.py`). The recipe then relocks and runs every
check. `LICENSE` is never changed, since the MIT licence requires its notice to stay with the
code. A test rebrands a copy of the repository and runs the copy's whole suite, so the rename
keeps working as the code grows.

Replace the README's logo, badges and footer by hand: they point at Libre DevOps and this
repository's GitHub pages.

## A logo in the banner

`--banner-picture FILE` puts a small picture above the banner's words: a logo in its own
colours. The file is plain text, a palette and then rows of pixels:

```text
# a letter, its colour, and the character drawn without colour
p #1E3A8A :
r #F97316 #
---
..pppp..
.pprrpp.
.pprrpp.
..pppp..
```

Each row is a row of pixels, all as wide, and `.` is no pixel. On a terminal with colour,
each line draws two rows with half blocks, so the pixels come out about square, in 24-bit
colour where the terminal says it can (`COLORTERM`, or Windows Terminal) and the nearest of
the 256 colours elsewhere. Without colour (`NO_COLOR`, a pipe, a log), or where the output
cannot show the blocks, each colour's character draws it instead, so the shape survives
in plain ASCII. With a picture, the banner's words are printed in bold, not the rainbow.

A picture about 30 to 40 pixels wide suits an 80-column terminal. To make one from a logo,
shrink it to that width, give each pixel the nearest of a few colours, and write each
colour's letter.
