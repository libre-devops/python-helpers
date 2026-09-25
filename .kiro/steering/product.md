---
inclusion: always
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# What this is

`ldo` (distribution `libre-devops-helpers`, import `libre_devops_helpers`): a fast, read-only
CLI and library for Microsoft (Entra ID, Defender XDR, Intune, Azure, Graph, PIM, Logic Apps,
Automation) and ServiceNow. Its users are people signing in as themselves, usually through
the Azure CLI; automation is second. Everything reads, apart from `ldo az use`, which switches
the Azure CLI's account. Never add a command that changes a tenant or an instance without
being asked.
