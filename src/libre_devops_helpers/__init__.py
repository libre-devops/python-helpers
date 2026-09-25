"""Libre DevOps Helpers: helpers and a CLI for Azure, Entra, Defender and more.

Subpackages, lowest layer first, in the style of the LibreDevOpsHelpers nested
PowerShell modules:

- ``core``          everything shared: errors, config and clouds, credentials, the az
                    runner, HTTP client, token checks, polling, inputs, logging
- ``azcli``         Azure CLI accounts, sign-in and switching between profiles
- ``entra``         Entra ID: devices, users, groups, roles, sign-ins, apps, policies
- ``xdr``           Defender for Endpoint: machines, alerts, vulnerabilities, hunting
- ``intune``        Intune managed devices and compliance
- ``azure``         Azure Resource Manager: Resource Graph, RBAC, Defender for Cloud
- ``keyvault``      Key Vault secret, certificate and key metadata
- ``loganalytics``  KQL against Log Analytics workspaces
- ``devices``       devices across Entra, Defender and Intune: check, watch, show
- ``cli``           the ``ldo`` command, a thin layer over the packages above

Feature modules depend on ``core`` only; ``devices`` also uses ``entra``, ``xdr`` and
``intune``. Every client takes any token provider, so where tokens come from is the
caller's choice.
"""

__version__ = "0.5.0"
