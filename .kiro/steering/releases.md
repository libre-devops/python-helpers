---
inclusion: always
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# Commits and releases

- Do not commit, push, tag or release until the person asks. Use their own git identity.
- Every branch and tag is mirrored to GitLab (`gitlab-mirror.yml`, see
  `docs/development.md`). Never push to the GitLab copy: the next run overwrites it. Its
  `.gitlab-ci.yml` does what the GitHub workflows do; a change to one goes in the other,
  and `tests/project/test_gitlab_ci.py` keeps their versions in step.
- No AI attribution in commits or pull requests: no `Co-Authored-By` or "Generated with"
  lines.
- Before a release, the person runs `ldo self-test` (hidden) in a real tenant; a CRASH or
  usage row there is a bug to fix first. Rename anything from their tenant before it goes
  in a test.
- A release is `just release` after the version is set in `pyproject.toml` and
  `src/libre_devops_helpers/__init__.py` and `CHANGELOG.md` has its section; see
  `docs/development.md`. Never move or reuse a released tag, and remember a PyPI version can
  never be replaced.
