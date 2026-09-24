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

- [ ] `just check` passes locally (ruff lint, format check and pytest)
- [ ] `just test-311` passes (the oldest supported Python)
- [ ] New behaviour is covered by tests that use the fakes, not the network or a real `az`
- [ ] Manually run against a real tenant (say which commands)
- [ ] GitHub Actions pipeline passed

## Checklist

- [ ] Code follows project conventions (see CONTRIBUTING.md)
- [ ] README updated for any new command, option or exit code
- [ ] CHANGELOG.md updated
- [ ] No tokens, tenant ids, subscription ids or real host names included (gitleaks checks)
- [ ] No hard-coded tool names; they come from `core/brand.py` (the rebrand test checks)
- [ ] Changes are scoped appropriately
