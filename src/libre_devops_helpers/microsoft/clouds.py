"""Microsoft cloud environments and the endpoints each one uses.

A profile names its cloud (``public`` unless set), and every client takes its base URL
and token resource from here, so nothing else in the package hard-codes a host. The
Azure CLI must be pointed at the same cloud (``az cloud set``) for its tokens to work.
"""

from __future__ import annotations

from dataclasses import dataclass

from libre_devops_helpers.core.errors import ConfigError


@dataclass(frozen=True)
class Cloud:
    """The endpoints of one Microsoft cloud. ``mde_url`` is None where Defender is absent."""

    name: str
    description: str
    login_url: str
    graph_url: str
    arm_url: str
    # The older ARM audience that some tokens still carry.
    arm_classic_url: str
    mde_url: str | None
    log_analytics_url: str
    keyvault_suffix: str

    def require_mde(self) -> str:
        """The Defender for Endpoint API URL, or ConfigError where this cloud has none."""
        if self.mde_url is None:
            raise ConfigError(f"Defender for Endpoint is not available in the {self.name} cloud")
        return self.mde_url


PUBLIC = Cloud(
    name="public",
    description="Azure public cloud",
    login_url="https://login.microsoftonline.com",
    graph_url="https://graph.microsoft.com",
    arm_url="https://management.azure.com",
    arm_classic_url="https://management.core.windows.net",
    mde_url="https://api.securitycenter.microsoft.com",
    log_analytics_url="https://api.loganalytics.io",
    keyvault_suffix="vault.azure.net",
)

USGOV = Cloud(
    name="usgov",
    description="Azure US Government (GCC High)",
    login_url="https://login.microsoftonline.us",
    graph_url="https://graph.microsoft.us",
    arm_url="https://management.usgovcloudapi.net",
    arm_classic_url="https://management.core.usgovcloudapi.net",
    mde_url="https://api-gov.securitycenter.microsoft.us",
    log_analytics_url="https://api.loganalytics.us",
    keyvault_suffix="vault.usgovcloudapi.net",
)

CHINA = Cloud(
    name="china",
    description="Azure operated by 21Vianet",
    login_url="https://login.chinacloudapi.cn",
    graph_url="https://microsoftgraph.chinacloudapi.cn",
    arm_url="https://management.chinacloudapi.cn",
    arm_classic_url="https://management.core.chinacloudapi.cn",
    mde_url=None,
    log_analytics_url="https://api.loganalytics.azure.cn",
    keyvault_suffix="vault.azure.cn",
)

CLOUDS: dict[str, Cloud] = {cloud.name: cloud for cloud in (PUBLIC, USGOV, CHINA)}


def get_cloud(name: str) -> Cloud:
    """A cloud by name. Raises ConfigError listing the known names when absent."""
    try:
        return CLOUDS[name.strip().lower()]
    except KeyError:
        raise ConfigError(
            f"unknown cloud {name!r}", hint=f"use one of {', '.join(CLOUDS)}"
        ) from None
