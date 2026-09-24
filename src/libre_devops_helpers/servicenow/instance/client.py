"""Questions about the instance: who am I, which roles, which release, which applications."""

from __future__ import annotations

from libre_devops_helpers.core.errors import ApiError, NotFoundError
from libre_devops_helpers.servicenow.instance.models import Application, AppStatus, Release, User
from libre_devops_helpers.servicenow.tables import TableClient, condition

# Security Incident Response: its plugin, its application scope and its main table.
SIR_PLUGIN = "com.snc.security_incident"
SIR_SCOPE = "sn_si"
SIR_TABLE = "sn_si_incident"


class InstanceClient:
    """Reads the instance's own records through the Table API."""

    def __init__(self, tables: TableClient) -> None:
        self.tables = tables

    def current_user(self, user_name: str | None = None) -> User:
        """The signed-in user, as the instance sees it; or the user called ``user_name``."""
        # gs.getUserID() is one of the functions an encoded query may call, and it names
        # whoever the request is authenticated as, however they signed in.
        query = (
            condition("user_name", user_name) if user_name else "sys_id=javascript:gs.getUserID()"
        )
        record = self.tables.first("sys_user", query=query, fields=User.FIELDS)
        if record is None:
            who = f"named {user_name!r}" if user_name else "for this sign-in"
            raise NotFoundError(f"no ServiceNow user {who}")
        return User.from_record(record)

    def roles(self, user: User) -> tuple[str, ...]:
        """Every role the user holds, directly or through a group or another role."""
        rows = self.tables.records(
            "sys_user_has_role",
            query=f"{condition('user', user.sys_id)}^state=active",
            fields=("role.name",),
        )
        return tuple(sorted({str(row.get("role.name")) for row in rows if row.get("role.name")}))

    def release(self) -> Release | None:
        """The release, or None when this account may not read system properties."""
        try:
            rows = self.tables.records(
                "sys_properties",
                query="nameINglide.buildtag.last,glide.war",
                fields=("name", "value"),
            )
        except ApiError as exc:
            if exc.status == 403:
                return None
            raise
        values = {str(row.get("name")): str(row.get("value") or "") for row in rows}
        # glide.buildtag.last is not kept as a record on every release; glide.war is.
        tag = values.get("glide.buildtag.last") or values.get("glide.war")
        return Release.from_build_tag(tag) if tag else None

    def applications(
        self, search: str | None = None, *, active_only: bool = True
    ) -> list[Application]:
        """Scoped applications, by name or scope, active ones first."""
        query = None
        if search:
            query = f"{condition('name', search, 'LIKE')}^OR{condition('scope', search, 'LIKE')}"
        found = [
            Application.from_record(row)
            for row in self.tables.records("sys_scope", query=query, fields=Application.FIELDS)
        ]
        if active_only:
            found = [app for app in found if app.active]
        return sorted(found, key=lambda app: (not app.active, app.name.casefold()))

    def table_exists(self, name: str) -> bool:
        return (
            self.tables.first("sys_db_object", query=condition("name", name), fields=("name",))
            is not None
        )

    def security_incident_response(self) -> AppStatus:
        """Whether Security Incident Response is installed: its table is the proof."""
        name = "Security Incident Response"
        if not self.table_exists(SIR_TABLE):
            return AppStatus(name, False, detail=f"no {SIR_TABLE} table")
        app = self.tables.first(
            "sys_scope", query=condition("scope", SIR_SCOPE), fields=("version", "active")
        )
        if app is not None:
            return AppStatus(name, True, str(app.get("version") or ""), f"application {SIR_SCOPE}")
        return AppStatus(name, True, detail=f"table {SIR_TABLE}")
