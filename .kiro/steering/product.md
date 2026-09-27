---
inclusion: always
---

<!-- Generated from AI.md by 'just ai'. Edit AI.md, not this file. -->

# What this is

`ldo` (distribution `libre-devops-helpers`, import `libre_devops_helpers`): a fast, read-only
CLI and library for Microsoft (Entra ID, Defender XDR, Intune, Azure, Graph, PIM, Logic Apps,
Automation), ServiceNow, and Atlassian (Jira, Confluence), with helpers for Terraform
modules. Its users are people signing in as themselves, usually through the Azure CLI;
automation is second. Everything reads, apart from `ldo az use`, which switches the Azure
CLI's account, `ldo planner add-news --write` and `add-rollup --write`, which raise and
update Planner tasks, and `ldo terraform sort` and `docs`, which change a module's own files
(`--check` only reads). Never add a command that changes a tenant or an instance without
being asked.
