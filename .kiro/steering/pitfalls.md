---
inclusion: always
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# Pitfalls already met

- `.gitignore` rules match anywhere unless anchored with `/`; ruff and hatchling honour
  `.gitignore`, so an ignored folder is silently left out of linting and the wheel.
- The arm64 image is built under emulation: keep heavy work (such as compiling bytecode) in
  a `FROM --platform=$BUILDPLATFORM` stage.
- The Azure CLI pins some dependencies exactly. A fix it holds back is forced in
  `container/azure-cli/pyproject.toml` (see the comment there), then signed in with.
- Microsoft APIs return stale duplicates (devices share names), paginate with `nextLink`
  or `@odata.nextLink`, and answer 403 for a missing scope, a missing licence and a
  suspended tenant alike: say which in the hint (Graph's own codes are in
  `GRAPH_ERROR_HINTS`, `microsoft/api_clients.py`).
- Read an Azure resource id with `microsoft/resource_ids.py`, never by splitting on `/`. A
  Log Analytics workspace's resource id and its Workspace ID (a GUID) are different things,
  and people mix them up: `microsoft/workspaces.py` tells them apart.
- Two `ldo` commands can run at once. Anything they both write (the token cache) is changed
  under a lock file, with a temporary file of its own renamed into place.
