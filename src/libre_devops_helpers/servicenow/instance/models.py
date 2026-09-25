"""Records about the instance itself: the signed-in user, the release, and applications."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from libre_devops_helpers.core import fields

# glide-yokohama-12-18-2024__patch4-06-25-2025 (glide.buildtag.last), or the same with a
# .zip suffix (glide.war), for example.
_BUILD_TAG = re.compile(
    r"^glide-(?P<family>[a-z]+)-(?P<date>\d{2}-\d{2}-\d{4})(?:__(?P<patch>[a-z0-9]+))?"
)


def _flag(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "active", "yes"}


@dataclass(frozen=True)
class User:
    """A ``sys_user`` record."""

    sys_id: str
    user_name: str
    name: str
    email: str
    active: bool
    locked_out: bool
    web_service_only: bool
    last_login: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    FIELDS = (
        "sys_id",
        "user_name",
        "name",
        "email",
        "active",
        "locked_out",
        "web_service_access_only",
        "last_login_time",
    )

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> User:
        """A user as the Table API returns it."""
        return cls(
            sys_id=fields.text(record, "sys_id"),
            user_name=fields.text(record, "user_name"),
            name=fields.text(record, "name"),
            email=fields.text(record, "email"),
            active=_flag(record.get("active")),
            locked_out=_flag(record.get("locked_out")),
            web_service_only=_flag(record.get("web_service_access_only")),
            last_login=fields.text(record, "last_login_time"),
            raw=dict(record),
        )


@dataclass(frozen=True)
class Release:
    """The instance's release, from its build tag: family, build date and patch."""

    build_tag: str
    family: str = ""
    build_date: str = ""
    patch: str = ""

    @classmethod
    def from_build_tag(cls, tag: str) -> Release:
        """A release from a build tag such as ``glide-zurich-07-01-2025__patch4``; a tag of another
        shape is kept as it is."""
        match = _BUILD_TAG.match(tag.strip())
        if not match:
            return cls(build_tag=tag)
        return cls(
            build_tag=tag,
            family=match["family"].capitalize(),
            build_date=match["date"],
            patch=match["patch"] or "",
        )

    @property
    def label(self) -> str:
        """The release as people say it (``Zurich patch4``), else its build tag."""
        if not self.family:
            return self.build_tag or "unknown"
        return f"{self.family} {self.patch}".strip()


@dataclass(frozen=True)
class Application:
    """A scoped application (``sys_scope``): from the ServiceNow Store, or built here.

    The plugin tables (``v_plugin``, ``sys_plugins``, ``sys_store_app``) refuse the REST
    API even to admin, but every scoped application, Security Incident Response
    (``sn_si``) among them, is listed in ``sys_scope``, which it may read.
    """

    scope: str
    name: str
    active: bool
    version: str
    kind: str  # "store app" or "custom app"
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    FIELDS = ("scope", "name", "active", "version", "sys_class_name")

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Application:
        """An installed application as the Table API returns it: a store app or a custom one."""
        return cls(
            scope=fields.text(record, "scope"),
            name=fields.text(record, "name"),
            active=_flag(record.get("active")),
            version=fields.text(record, "version"),
            kind="store app" if record.get("sys_class_name") == "sys_store_app" else "custom app",
            raw=dict(record),
        )


@dataclass(frozen=True)
class AppStatus:
    """Whether an application is on the instance, and how we know."""

    name: str
    installed: bool
    version: str = ""
    detail: str = ""
