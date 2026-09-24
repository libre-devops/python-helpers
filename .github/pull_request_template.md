## Summary

Brief description of the change.

## Type of Change

- [ ] Bug fix
- [ ] New feature or command
- [ ] Enhancement / improvement
- [ ] Documentation update
- [ ] Refactor
- [ ] CI / pipeline change
- [ ] Dependency update

## Testing

Describe how this was tested.

- [ ] `just ci` passes locally (lint, format check, tests with coverage, Python 3.11, audit, build)
- [ ] New behaviour is covered by tests that use the fakes, not the network or a real `az`
- [ ] Tests sit in the directory that mirrors the code under test
- [ ] If the Containerfile or its inputs changed: `just image`, `just image-slim` and
      `just image-scan` pass
- [ ] Manually run against a real tenant (say which commands)
- [ ] GitHub Actions pipeline passed

## Checklist

- [ ] Code follows project conventions (see CONTRIBUTING.md)
- [ ] `docs/` updated for any new command, option or exit code (and the README's table for a new group)
- [ ] CHANGELOG.md updated
- [ ] No tokens, tenant ids, subscription ids or real host names included (gitleaks checks)
- [ ] No hard-coded tool names; they come from `core/brand.py` (the rebrand test checks)
- [ ] Changes are scoped appropriately
