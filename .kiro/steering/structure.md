---
inclusion: always
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# Layout and layering

```text
src/libre_devops_helpers/
  core/                 vendor-neutral: errors, config, brand, HTTP client, network (proxy
                        rules) and probe (testing the way out), trust (certificates), token
                        store, polling, inputs (CSV and Excel), logging, YAML writer,
                        sorting, colour
  microsoft/            the shared Microsoft layer: clouds, credentials, tokens, profiles,
                        and the Graph and Resource Manager client bases (api_clients.py)
  microsoft/<feature>/  one package per API: entra, xdr, graph, azure, pim, detections ...
  microsoft/devices/    the one composite, using entra, xdr and intune
  servicenow/           the ServiceNow vendor, same shape
  cli/                  the ldo command: parses, calls a client, renders. No logic here.
                        A command group too big for one file is a package (devices,
                        entra, logicapp, xdr) whose modules each register their own commands.
```

`tests/project/test_package_surface.py` enforces the layering: `core` imports nothing of
ours, a feature imports only `core` and its vendor layer, `cli` sits on top. Cross-cutting
code (auth, HTTP, input parsing) goes in `core` or the vendor layer, never in a feature. A new
feature package needs its entry in that test, a `REQUIREMENTS` tuple, and a test folder.
