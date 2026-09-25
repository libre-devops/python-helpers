"""A tenant, and a ServiceNow instance, that answer every read-only command.

For the JSON output test: each API answers with a record or two shaped as the real one
does, so every command runs end to end and writes each of its fields. It is built from
the other fakes where they already hold the data (Automation, ServiceNow, incidents,
PIM) and answers the rest here.
"""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

from fakes.automation import FakeAutomation
from fakes.azcli import account_json, az_runner
from fakes.detections import rule as detection_rule
from fakes.http import fake_session, json_body
from fakes.ids import CLIENT_ID, SUBSCRIPTION, TENANT
from fakes.incidents import incident
from fakes.logicapps import CODE_VIEW
from fakes.pim import RULES
from fakes.servicenow import CLIENT_ID as SERVICENOW_CLIENT
from fakes.servicenow import (
    CLIENT_SECRET,
    INSTANCE,
    PASSWORD,
    USERNAME,
    FakeInstance,
)
from fakes.tenant import az_responder, runner
from fakes.tokens import graph_claims, make_jwt
from libre_devops_helpers.cli import app
from libre_devops_helpers.cli.runtime import Runtime
from libre_devops_helpers.core.token_store import MemoryStore

NOW = datetime.now(UTC)
USER_ID = "88888888-8888-8888-8888-888888888888"
GROUP_ID = "55555555-5555-5555-5555-555555555555"
DEVICE_ID = "66666666-6666-6666-6666-666666666666"
MACHINE_ID = "a" * 40
WORKSPACE = "abababab-abab-abab-abab-abababababab"
# ServiceNow's profile from the environment, signing in with OAuth's password grant.
SERVICENOW = {
    "SNOW_INSTANCE_URL": INSTANCE,
    "SNOW_INSTANCE_USERNAME": USERNAME,
    "SNOW_INSTANCE_PASSWORD": PASSWORD,
    "SNOW_CLIENT_ID": SERVICENOW_CLIENT,
    "SNOW_CLIENT_SECRET": CLIENT_SECRET,
}
CONFIG = f"""
[microsoft]
default_profile = "tenant"

[microsoft.profiles.tenant]
tenant_id = "{TENANT}"
subscription_id = "{SUBSCRIPTION}"
workspace_id = "{WORKSPACE}"
"""


def iso(days: float = 0) -> str:
    return (NOW + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Everything:
    """Answers every read-only call, by host and path; anything else fails the test."""

    def __init__(self) -> None:
        self.automation = FakeAutomation()
        self.instance = FakeInstance()
        self.requests: list = []

    def __call__(self, request):
        self.requests.append(request)
        parts = urlsplit(request.url)
        host, path = parts.netloc, unquote(parts.path)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if host == urlsplit(INSTANCE).netloc:
            return self.instance(request)
        if host == "login.microsoftonline.com":
            token = make_jwt(graph_claims(appid=CLIENT_ID))
            return (200, {"access_token": token, "expires_in": 3600})
        answer = {
            "graph.microsoft.com": self.graph,
            "api.securitycenter.microsoft.com": self.defender,
            "management.azure.com": self.arm,
            "api.loganalytics.io": self.logs,
            "kv-app.vault.azure.net": self.vault,
        }.get(host)
        if answer is None:
            raise AssertionError(f"unexpected request {unquote(request.url)}")
        return answer(request, path, query)

    # Graph ---------------------------------------------------------------------------

    def graph(self, request, path: str, query: dict[str, str]):
        path = path.removeprefix("/v1.0").removeprefix("/beta")
        wanted = query.get("$filter", "")
        named = wanted.split("'")[1] if "'" in wanted else ""
        if path in {"/me", f"/users/{USER}", f"/users/{USER_ID}"}:
            return (200, _user())
        if path == "/organization":
            return (200, {"value": [{"id": TENANT, "displayName": "Contoso"}]})
        if path == "/users":
            return (200, {"value": [_user()]})
        if path == "/devices":
            return (200, {"value": [_device()] if named in {"", "web01"} else []})
        if path == "/groups":
            return (200, {"value": [_group()] if named in {"", GROUP_NAME} else []})
        if path == f"/groups/{GROUP_ID}":
            return (200, _group())
        if path.startswith(f"/groups/{GROUP_ID}/"):
            return self.group_members(path)
        if path.endswith("/transitiveMemberOf/microsoft.graph.group") or path.endswith(
            "/memberOf/microsoft.graph.group"
        ):
            return (200, {"value": [_group()]})
        if path.endswith("/microsoft.graph.directoryRole"):
            return (200, {"value": [_directory_role()]})
        if path.startswith("/roleManagement/directory/"):
            return self.directory_roles(path)
        if path.startswith("/identityGovernance/privilegedAccess/group/"):
            return self.pim_groups(path)
        if path.startswith("/policies/roleManagementPolicyAssignments"):
            return (200, {"value": [{"policy": {"rules": RULES}}]})
        if path == "/auditLogs/signIns":
            return (200, {"value": [_sign_in()]})
        if path == "/identity/conditionalAccess/policies":
            return (200, {"value": [_ca_policy()]})
        if path == "/applications":
            return (200, {"value": [_application()]})
        if path == "/servicePrincipals":
            return (200, {"value": [_service_principal()]})
        if path == "/deviceManagement/managedDevices":
            return (200, {"value": [_managed_device()]})
        if path == "/security/runHuntingQuery":
            return (200, self.hunt(json_body(request)["Query"]))
        if path == "/security/incidents":
            return (200, {"value": [_incident(1), _incident(2, severity="medium")]})
        if path == "/security/rules/detectionRules":
            return (200, {"value": [detection_rule(), detection_rule("8", status="autoDisabled")]})
        if path == "/security/rules/detectionRules/7506":
            return (200, detection_rule())
        if path == "/security/incidents/1":
            return (200, _incident(1))
        raise AssertionError(f"unexpected Graph path {path}")

    def group_members(self, path: str):
        if path.endswith("/microsoft.graph.device"):
            return (200, {"value": [_device()]})
        return (200, {"value": [{**_device(), "@odata.type": "#microsoft.graph.device"}]})

    def directory_roles(self, path: str):
        if path.endswith("/roleDefinitions"):
            return (200, {"value": [{"id": ROLE_ID, "displayName": "Global Reader"}]})
        if path.endswith("Requests"):
            return (200, {"value": [_graph_request(roleDefinitionId=ROLE_ID)]})
        return (200, {"value": [_graph_assignment(roleDefinitionId=ROLE_ID)]})

    def pim_groups(self, path: str):
        if path.endswith("Requests"):
            return (200, {"value": [_graph_request(groupId=GROUP_ID, accessId="member")]})
        return (200, {"value": [_graph_assignment(groupId=GROUP_ID, accessId="member")]})

    def hunt(self, text: str) -> dict:
        """Advanced Hunting: the antivirus and timeline queries get their own columns;
        anything else one row."""
        if "| top " in text and "_events" in text:
            return _timeline(text)
        if "DeviceTvmInfoGathering" in text:
            row = {
                "DeviceId": MACHINE_ID,
                "DeviceName": "web01",
                "OSPlatform": "Linux",
                "Reported": iso(),
                "AvSignatureVersion": "1.419.100.0",
                "AvEngineVersion": "1.1.24000.4",
                "AvPlatformVersion": "101.24000.0001",
                "AvMode": "0",
                "SignatureUpToDate": True,
                "AssessmentContext": "[]",
            }
        else:
            row = {"DeviceName": "web01", "Timestamp": iso()}
        return {"schema": [{"name": key} for key in row], "results": [row]}

    # Defender for Endpoint ---------------------------------------------------------------

    def defender(self, request, path: str, query: dict[str, str]):
        if path == "/api/machines":
            return (200, {"value": [_machine()]})
        if path == f"/api/machines/{MACHINE_ID}/vulnerabilities":
            return (200, {"value": [_vulnerability()]})
        if path == "/api/alerts":
            return (200, {"value": [_alert()]})
        if path == "/api/indicators":
            return (200, {"value": [_indicator()]})
        if path == "/api/advancedqueries/run":
            # The endpoint API's own casing: Schema and Name, Results.
            found = self.hunt(json_body(request)["Query"])
            schema = [{"Name": column["name"]} for column in found["schema"]]
            return (200, {"Schema": schema, "Results": found["results"]})
        raise AssertionError(f"unexpected Defender path {path}")

    # Azure Resource Manager --------------------------------------------------------------

    def arm(self, request, path: str, query: dict[str, str]):
        if "/providers/Microsoft.Automation/" in path or path == "/subscriptions":
            return self.automation.handler(request)
        security = f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Security"
        if path == "/providers/Microsoft.ResourceGraph/resources":
            rows = [{"name": "kv-app", "type": "microsoft.keyvault/vaults", "location": "uksouth"}]
            return (200, {"data": rows, "totalRecords": 1})
        if path == f"{security}/secureScores/ascScore":
            score = {"current": 41.5, "max": 58, "percentage": 0.7155}
            return (200, {"id": "ascScore", "properties": {"score": score}})
        if path == f"{security}/secureScoreControls":
            return (200, {"value": [_control()]})
        if path == f"{security}/assessments":
            return (200, {"value": [_assessment()]})
        if path == f"{security}/pricings":
            return (200, {"value": [_pricing()]})
        if path.endswith("/providers/Microsoft.Authorization/roleAssignments"):
            return (200, {"value": [_role_assignment()]})
        if "/providers/Microsoft.Authorization/roleDefinitions/" in path:
            return (200, {"id": path, "properties": {"roleName": "Reader"}})
        if path.endswith("/providers/Microsoft.Authorization/roleDefinitions"):
            return (200, {"value": [{"id": ROLE_DEFINITION, "properties": {"roleName": "Owner"}}]})
        if path.endswith("/roleManagementPolicyAssignments"):
            return (200, {"value": [{"properties": {"effectiveRules": RULES}}]})
        if "/providers/Microsoft.Authorization/role" in path:
            return self.azure_pim(path)
        if "/providers/Microsoft.Logic/" in path:
            return self.logic_apps(request, path)
        if path == APPS_GROUP:
            return (200, {"id": path, "name": "rg-apps", "location": "uksouth"})
        raise AssertionError(f"unexpected ARM path {path}")

    def azure_pim(self, path: str):
        if path.endswith("Requests"):
            return (200, {"value": [_arm_pim("Owner", status="PendingApproval")]})
        if path.endswith("roleAssignmentScheduleInstances"):
            return (200, {"value": [_arm_pim("Reader", assignment_type="Activated")]})
        return (200, {"value": [_arm_pim("Owner", ends=iso(90))]})

    def logic_apps(self, request, path: str):
        workflows = f"{APPS_GROUP}/providers/Microsoft.Logic/workflows"
        if path == workflows:
            return (200, {"value": [_workflow()]})
        if path == f"{workflows}/orders":
            return (200, _workflow())
        if path.endswith("/validate"):
            return (200, b"", {"Content-Type": "application/json"})
        raise AssertionError(f"unexpected Logic Apps path {path}")

    # Log Analytics and Key Vault -----------------------------------------------------------

    def logs(self, request, path: str, query: dict[str, str]):
        if path == f"/v1/workspaces/{WORKSPACE}/query":
            if json_body(request)["query"].startswith("Usage\n"):
                return (200, {"tables": [_usage()]})
            columns = [{"name": "Computer", "type": "string"}, {"name": "Count", "type": "long"}]
            return (200, {"tables": [{"columns": columns, "rows": [["web01", 3]]}]})
        raise AssertionError(f"unexpected Log Analytics path {path}")

    def vault(self, request, path: str, query: dict[str, str]):
        base = "https://kv-app.vault.azure.net"
        items = {
            "/secrets": [{"id": f"{base}/secrets/db", "contentType": "text/plain"}],
            "/certificates": [{"id": f"{base}/certificates/web"}],
            "/keys": [{"kid": f"{base}/keys/signing"}],
        }
        if path not in items:
            raise AssertionError(f"unexpected Key Vault path {path}")
        attributes = {
            "enabled": True,
            "exp": int((NOW + timedelta(days=5)).timestamp()),
            "nbf": int((NOW - timedelta(days=360)).timestamp()),
            "updated": int((NOW - timedelta(days=30)).timestamp()),
        }
        return (200, {"value": [{**item, "attributes": attributes} for item in items[path]]})


# The records ---------------------------------------------------------------------------------

USER = "ana@example.com"
GROUP_NAME = "Linux servers"
ROLE_ID = "62e90394-69f5-4237-9190-012177145e10"
ROLE_DEFINITION = "/providers/Microsoft.Authorization/roleDefinitions/o"
APPS_GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-apps"


def _user() -> dict:
    return {
        "id": USER_ID,
        "displayName": "Ana",
        "userPrincipalName": USER,
        "mail": USER,
        "jobTitle": "Engineer",
        "accountEnabled": True,
        "userType": "Member",
        "onPremisesSyncEnabled": None,
    }


def _device() -> dict:
    return {
        "id": DEVICE_ID,
        "displayName": "web01",
        "deviceId": "77777777-7777-7777-7777-777777777777",
        "operatingSystem": "Linux",
        "operatingSystemVersion": "22.04",
        "accountEnabled": True,
        "trustType": "ServerAd",
        "approximateLastSignInDateTime": iso(-1),
    }


def _group() -> dict:
    return {
        "id": GROUP_ID,
        "displayName": GROUP_NAME,
        "description": "Every Linux server",
        "groupTypes": [],
        "securityEnabled": True,
        "mailEnabled": False,
        "membershipRule": None,
    }


def _directory_role() -> dict:
    return {"id": "r1", "displayName": "Global Reader", "roleTemplateId": ROLE_ID}


def _graph_assignment(**extra) -> dict:
    return {
        "id": "a1",
        "principalId": USER_ID,
        "directoryScopeId": "/",
        "memberType": "Direct",
        "assignmentType": "Activated",
        "startDateTime": iso(-1),
        "endDateTime": iso(1),
        **extra,
    }


def _graph_request(**extra) -> dict:
    return {
        "id": "q1",
        "principalId": USER_ID,
        "directoryScopeId": "/",
        "action": "selfActivate",
        "status": "PendingApproval",
        "justification": "deploy 12",
        "createdDateTime": iso(-0.1),
        "scheduleInfo": {"startDateTime": iso(), "expiration": {"duration": "PT8H"}},
        **extra,
    }


def _arm_pim(role: str, *, ends: str | None = None, assignment_type: str = "", status: str = ""):
    return {
        "id": f"/x/{role}",
        "properties": {
            "principalId": USER_ID,
            "memberType": "Direct",
            "assignmentType": assignment_type,
            "status": status,
            "requestType": "SelfActivate",
            "justification": "deploy 12",
            "createdOn": iso(-0.1),
            "startDateTime": iso(-1),
            "endDateTime": ends,
            "roleDefinitionId": ROLE_DEFINITION,
            "scope": f"/subscriptions/{SUBSCRIPTION}",
            "expandedProperties": {
                "roleDefinition": {"displayName": role, "id": ROLE_DEFINITION},
                "scope": {"displayName": "Production", "id": f"/subscriptions/{SUBSCRIPTION}"},
                "principal": {"displayName": "Ana", "id": USER_ID},
            },
        },
    }


def _sign_in() -> dict:
    return {
        "id": "s1",
        "createdDateTime": iso(-0.05),
        "userPrincipalName": USER,
        "appDisplayName": "Azure Portal",
        "ipAddress": "203.0.113.7",
        "clientAppUsed": "Browser",
        "conditionalAccessStatus": "success",
        "status": {"errorCode": 0, "failureReason": None},
        "deviceDetail": {"displayName": "web01", "operatingSystem": "Linux"},
        "location": {"city": "London", "countryOrRegion": "GB"},
    }


def _ca_policy() -> dict:
    return {
        "id": "p1",
        "displayName": "Require MFA for admins",
        "state": "enabled",
        "conditions": {
            "users": {"includeRoles": [ROLE_ID], "excludeUsers": []},
            "applications": {"includeApplications": ["All"]},
        },
        "grantControls": {"operator": "OR", "builtInControls": ["mfa"]},
        "sessionControls": None,
    }


def _application() -> dict:
    return {
        "id": "o1",
        "appId": "a1",
        "displayName": "billing-api",
        "passwordCredentials": [{"keyId": "k1", "displayName": "ci", "endDateTime": iso(3)}],
        "keyCredentials": [{"keyId": "k2", "displayName": "cert", "endDateTime": iso(20)}],
    }


def _service_principal() -> dict:
    return {"id": "sp1", "appId": "a1", "displayName": "billing-api", "accountEnabled": True}


def _managed_device() -> dict:
    return {
        "id": "m1",
        "deviceName": "web01",
        "operatingSystem": "Linux",
        "osVersion": "22.04",
        "complianceState": "compliant",
        "managementAgent": "mdm",
        "lastSyncDateTime": iso(-0.5),
        "enrolledDateTime": iso(-100),
        "azureADDeviceId": "77777777-7777-7777-7777-777777777777",
        "userPrincipalName": USER,
    }


def _machine() -> dict:
    return {
        "id": MACHINE_ID,
        "computerDnsName": "web01",
        "onboardingStatus": "Onboarded",
        "healthStatus": "Active",
        "lastSeen": iso(-0.1),
        "firstSeen": iso(-300),
        "osPlatform": "Linux",
        "osVersion": "22.04",
        "version": "101.24000.0001",
        "machineTags": ["linux-servers"],
        "riskScore": "Low",
        "exposureLevel": "Medium",
        "rbacGroupName": "Linux servers",
        "aadDeviceId": "77777777-7777-7777-7777-777777777777",
    }


def _vulnerability() -> dict:
    return {
        "id": "CVE-2026-0001",
        "name": "CVE-2026-0001",
        "severity": "High",
        "cvssV3": 8.1,
        "exploitVerified": False,
        "publicExploit": True,
        "publishedOn": iso(-30),
    }


def _alert() -> dict:
    return {
        "id": "da1",
        "title": "Suspicious process",
        "severity": "Medium",
        "status": "New",
        "category": "Execution",
        "detectionSource": "EDR",
        "machineId": MACHINE_ID,
        "computerDnsName": "web01",
        "incidentId": 1,
        "alertCreationTime": iso(-0.2),
        "lastEventTime": iso(-0.1),
    }


def _indicator() -> dict:
    return {
        "id": "i1",
        "indicatorValue": "203.0.113.9",
        "indicatorType": "IpAddress",
        "action": "Block",
        "title": "Known bad",
        "severity": "High",
        "expirationTime": iso(30),
        "createdBy": USER,
    }


def _control() -> dict:
    return {
        "name": "c1",
        "properties": {
            "displayName": "Enable MFA",
            "score": {"current": 5, "max": 10, "percentage": 0.5},
            "healthyResourceCount": 3,
            "unhealthyResourceCount": 2,
            "notApplicableResourceCount": 0,
        },
    }


def _assessment() -> dict:
    resource = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg/providers/Microsoft.Compute"
    resource += "/virtualMachines/vm1"
    return {
        "id": f"{resource}/providers/Microsoft.Security/assessments/a1",
        "name": "a1",
        "properties": {
            "displayName": "Enable disk encryption",
            "status": {"code": "Unhealthy", "cause": "NotEncrypted"},
            "metadata": {"severity": "High"},
            "resourceDetails": {"Id": resource},
        },
    }


def _pricing() -> dict:
    return {
        "name": "VirtualMachines",
        "properties": {
            "pricingTier": "Standard",
            "subPlan": "P2",
            "freeTrialRemainingTime": "PT0S",
            "enablementTime": iso(-200),
        },
    }


def _role_assignment() -> dict:
    return {
        "id": "ra1",
        "properties": {
            "scope": f"/subscriptions/{SUBSCRIPTION}",
            "roleDefinitionId": "/providers/Microsoft.Authorization/roleDefinitions/r",
            "principalId": USER_ID,
            "principalType": "User",
            "condition": None,
        },
    }


def _usage() -> dict:
    """The Usage table, summarised as the ingestion query asks: one quiet table, one not."""
    names = ["DataType", "LastData", "Megabytes", "BillableMegabytes", "Solutions"]
    rows = [
        ["CommonSecurityLog", iso(-3), 5000.0, 5000.0, "Security"],
        ["Heartbeat", iso(-0.05), 10.0, 0.0, "LogManagement"],
    ]
    return {"columns": [{"name": name} for name in names], "rows": rows}


def _timeline(text: str) -> dict:
    """A process started, and the alert it raised, as the timeline query shapes them."""
    common = {"Account": "root", "DeviceName": "web01", "DeviceId": MACHINE_ID}
    rows = [
        {
            "Timestamp": iso(-0.01),
            "Type": "alert",
            "ActionType": "High",
            "Detail": "Suspicious process",
            "Process": "",
            "Id": "da1",
            **common,
        },
        {
            "Timestamp": iso(-0.02),
            "Type": "process",
            "ActionType": "ProcessCreated",
            "Detail": "bash -c id",
            "Process": "sshd",
            "Id": "42",
            **common,
        },
    ]
    return {"schema": [{"name": key} for key in rows[0]], "results": rows}


def _incident(number: int, **extra) -> dict:
    """An incident whose alerts name a device and a user, tagged by hand and by Defender."""
    record = incident(number, customTags=["pci"], systemTags=["Ransomware"], **extra)
    for alert in record["alerts"]:
        alert["evidence"] = [
            {"@odata.type": "#microsoft.graph.security.deviceEvidence", "deviceDnsName": "web01"},
            {
                "@odata.type": "#microsoft.graph.security.userEvidence",
                "userAccount": {"userPrincipalName": USER, "accountName": "ana"},
            },
        ]
    return record


def _workflow() -> dict:
    return {
        "id": f"{APPS_GROUP}/providers/Microsoft.Logic/workflows/orders",
        "name": "orders",
        "location": "uksouth",
        "properties": {
            "definition": CODE_VIEW["definition"],
            "parameters": {"ticket_prefix": {"value": "INC"}},
        },
    }


def azure_cli(args: list[str]) -> tuple[int, str, str]:
    """The Azure CLI, signed in to the tenant's one subscription."""
    if args[:2] == ["account", "show"]:
        return (0, json.dumps(account_json(SUBSCRIPTION, TENANT, default=True)), "")
    return az_responder(args)


def invoke(config_file, tenant: Everything, args, *, stdin=None):
    """Run a command against ``tenant``, with ServiceNow's env profile set up as well."""
    obj = Runtime(
        config_path=config_file,
        token_store=MemoryStore(),
        has_browser=lambda: False,
        open_browser=lambda url: None,
        az_runner=az_runner(azure_cli)[0],
        session=fake_session(tenant)[0],
        environ=dict(SERVICENOW),
    )
    obj.interactive = lambda: False
    return runner.invoke(app, args, obj=obj, input=stdin)
