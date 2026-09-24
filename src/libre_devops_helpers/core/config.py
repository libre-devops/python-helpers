"""The config file: one TOML file, with a section per vendor.

Its path is, in order: an explicit path, the ``LDO_CONFIG`` environment variable, then the
platform config directory (``~/.config/ldo/config.toml`` on Linux and macOS, under
``%APPDATA%`` on Windows). It lives outside any repository because it describes
environments, not code, and it never holds a secret.

The top level holds what every vendor shares (``ca_bundle``). Each vendor layer reads and
validates its own section (``[microsoft]``, ...) with the field readers here, so every
section rejects unknown keys and bad values the same way.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from libre_devops_helpers.core import brand
from libre_devops_helpers.core.errors import ConfigError, ConfigNotFoundError
from libre_devops_helpers.core.util import is_guid

CONFIG_HEADER = f"""\
# {brand.DISPLAY_NAME} ({brand.COMMAND}) configuration. Each vendor has its own section;
# every key is described in {brand.docs("configuration")}
#
# Optional PEM bundle for a TLS-inspecting proxy, used for every HTTPS call. Without it,
# SSL_CERT_FILE or the bundled CA list is used.
# ca_bundle = "~/certs/proxy-ca.pem"
"""

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class ConfigFile:
    """The parsed file: shared settings, plus each vendor's raw section."""

    path: Path
    data: Mapping[str, Any] = field(default_factory=dict)
    ca_bundle: Path | None = None

    def section(self, name: str) -> Mapping[str, Any] | None:
        """A vendor's section, or None when the file has none."""
        value = self.data.get(name)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ConfigError(f"{self.path}: [{name}] must be a table")
        return value


def default_config_path() -> Path:
    """Where the config file lives when no explicit path is given."""
    override = os.environ.get(brand.CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / brand.CONFIG_DIR / "config.toml"


def load_config_file(
    path: Path | None = None, *, sections: Iterable[str] | None = None
) -> ConfigFile:
    """Read and parse the config file. Raises ConfigNotFoundError when it is absent.

    ``sections`` names the vendor sections that may appear; anything else at the top
    level is then an error, so a typo fails loudly. None skips that check, for a library
    caller that only knows its own vendor.
    """
    path = path or default_config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigNotFoundError(
            f"config file not found: {path}",
            hint=f"create one with {brand.command('config init')}",
        ) from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from None
    return parse_config_file(data, path, sections=sections)


def parse_config_file(
    data: Mapping[str, Any], path: Path, *, sections: Iterable[str] | None = None
) -> ConfigFile:
    """Validate already-parsed TOML's shared settings."""
    where = str(path)
    if sections is not None:
        reject_unknown(data, frozenset({"ca_bundle", *sections}), where)
    ca_bundle = data.get("ca_bundle")
    if ca_bundle is not None and not isinstance(ca_bundle, str):
        raise ConfigError(f"{where}: ca_bundle must be a path string")
    return ConfigFile(
        path=path,
        data=dict(data),
        ca_bundle=Path(ca_bundle).expanduser() if ca_bundle else None,
    )


# Field readers for vendor sections --------------------------------------------------


def check_name(name: str, where: str) -> None:
    """Profile and instance names are lowercase, so they are easy to type and complete."""
    if not _NAME.match(name):
        raise ConfigError(f"{where}: use lowercase letters, digits, '-' and '_' in names")


def table(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected a table")
    return value


def guid(data: Mapping[str, Any], key: str, where: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not is_guid(value):
        raise ConfigError(f"{where}: {key} must be a GUID, got {value!r}")
    return value.strip().lower()


def text(data: Mapping[str, Any], key: str, where: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{where}: {key} must be a string")
    return value.strip()


def https_url(data: Mapping[str, Any], key: str, where: str) -> str | None:
    # Tokens are attached to every request, so plain http is never acceptable.
    value = text(data, key, where)
    if value is not None and not value.startswith("https://"):
        raise ConfigError(f"{where}: {key} must be an https:// URL")
    return value.rstrip("/") if value else None


def reject_unknown(data: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})"
        )
