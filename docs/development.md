# Development

[Back to the docs](README.md)

You need [uv](https://docs.astral.sh/uv/). `uv sync` also installs `just` into the project
environment, so `uv run just ...` works without installing it.

```bash
just sync                  # install everything into .venv
just check                 # lint, format check, tests with coverage: what every change must pass
just ci                    # all of CI's checks: the above, Python 3.11, the audit and the build
just test -k devices       # extra args go to pytest
just fmt                   # apply formatting and safe lint fixes
just run devices check web01   # run ldo from the working tree
just install               # put the working tree's ldo on PATH
just lock                  # relock the tool and the image's Azure CLI
just secrets               # the secret scan, uncommitted changes included (needs gitleaks)
```

Run `just` for the full list. See [CONTRIBUTING.md](../CONTRIBUTING.md) before opening a pull
request.

## Tests

The tests mirror the package (`tests/core`, `tests/microsoft/<feature>`, `tests/cli`,
`tests/cli/commands`), one test module per module, with shared fakes in `tests/fakes`, one
module per concern. `tests/project` tests the project itself: the layering, the rebrand, the
layout, and that every example in these docs is a command that exists. Tests never touch the
network, a real `az` or a real clock, so an hour-long watch runs in microseconds.

## CI

| Workflow | What it does |
| --- | --- |
| `ci.yml` | gitleaks over every commit, ruff, pip-audit, pytest on Python 3.11 to 3.14 (and Windows and macOS), coverage against the floor in `pyproject.toml`, and the build |
| `container.yml` | builds both images for amd64 and arm64, smoke tests and scans the native ones, and publishes on a release or the weekly patch run |
| `release.yml` | on a `v*` tag: CI, then the images, then the GitHub release of the files CI built |
| `badges.yml` | after a passing run on `main`, publishes the coverage badge to the `badges` branch |
| `codeql.yml`, `dependency-review.yml` | CodeQL on every change and weekly; dependency review on pull requests |

Third-party actions are pinned to a commit. Container findings with a fix go to the Security
tab; the full scan is kept with each run.

## Releasing

1. Set the version in `pyproject.toml` and `src/libre_devops_helpers/__init__.py` (a test
   keeps them equal), run `just lock`, turn `## Unreleased` in `CHANGELOG.md` into
   `## <version>`, and move the pinned install lines in the docs to it (a test names any
   left behind).
2. Merge to `main` and let CI pass.
3. `just release`: it checks the tree is clean and in step with `origin/main`, that the
   changelog has the version and the tag is new, then tags and pushes.

The release workflow runs CI again as a gate, builds, scans and pushes both images with
attestations, and only then creates the GitHub release with the wheel, sdist and
`SHA256SUMS`. A release never exists without its images.

Last, when the repository variable `PUBLISH_PYPI` is `true`, it publishes the same wheel and
sdist to PyPI through [trusted publishing](https://docs.pypi.org/trusted-publishers/): PyPI
trusts `release.yml` running in the `pypi` environment, so no token is stored anywhere, and
the upload carries signed provenance. A version on PyPI can never be replaced, which is why
it goes last. To set it up once:

1. On pypi.org, add a trusted (pending, before the first upload) publisher: project
   `libre-devops-helpers`, owner `libre-devops`, repository `python-helpers`, workflow
   `release.yml`, environment `pypi`.
2. In the repository's settings, create the `pypi` environment, limited to `v*` tags.
3. `gh variable set PUBLISH_PYPI --body true`, then release as usual.

PyPI gets the README with its relative links pointed at GitHub (the `fancy-pypi-readme`
build hook in `pyproject.toml`); a test checks each lands on a file.

## Patching

Updates reach the images three ways:

1. **Debian packages.** Every Monday the container workflow rebuilds the latest release on
   the same pinned base with the newest Debian security updates, and republishes only when a
   package changed. Floating tags move; each build also gets its own stamped tag.
2. **Base images.** Dependabot moves the `python` and `uv` image digests.
3. **Python dependencies and the Azure CLI.** Dependabot bumps both lock files.

Routes 2 and 3 ship with the next release, so cut a patch release after merging them. When
the Azure CLI pins a dependency that has a fixed vulnerability, force the fix in
`container/azure-cli/pyproject.toml` (the comment there says how) and sign in with the image
before releasing.
