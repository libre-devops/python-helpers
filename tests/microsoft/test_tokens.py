from datetime import UTC, datetime

import pytest

from fakes.ids import OTHER_TENANT, TENANT
from fakes.tokens import graph_claims, make_jwt
from libre_devops_helpers.core.errors import TokenError
from libre_devops_helpers.microsoft.resources import GRAPH, MDE, Requirement
from libre_devops_helpers.microsoft.tokens import decode_token, passed, validate_token

DEVICES = Requirement("devices", "graph", (("Device.Read.All", "Directory.Read.All"),))

GROUPS = Requirement("groups", "graph", (("GroupMember.Read.All", "Directory.Read.All"),))

POLICIES = Requirement("policies", "graph", (("Policy.Read.All",),))

MACHINES = Requirement("machines", "mde", (("Machine.Read.All",),))

REQUIREMENTS = (DEVICES, GROUPS, POLICIES, MACHINES)


def statuses(checks):
    return {check.name: check.status for check in checks}


def test_decode_reads_claims_and_accepts_a_bearer_prefix():
    decoded = decode_token("Bearer " + make_jwt(graph_claims()))
    assert decoded.audiences == ("https://graph.microsoft.com",)
    assert decoded.tenant_id == TENANT
    assert decoded.principal == "analyst@example.com"
    assert decoded.scopes == ("Device.Read.All", "GroupMember.Read.All")
    assert decoded.identity_type == "user"
    assert decoded.expires_at is not None
    assert decoded.expires_at > datetime.now(UTC)


@pytest.mark.parametrize(
    ("token", "message"),
    [
        ("abc", "three dot-separated"),
        ("a.b.c.d.e", "encrypted"),
        ("!!!.???.sig", "cannot decode"),
    ],
)
def test_decode_rejects_malformed_tokens(token, message):
    with pytest.raises(TokenError, match=message):
        decode_token(token)


def test_a_healthy_graph_token_passes_every_check():
    checks = validate_token(
        decode_token(make_jwt(graph_claims())),
        resource=GRAPH,
        tenant_id=TENANT,
        requirements=(DEVICES, GROUPS),
    )
    assert set(statuses(checks).values()) == {"pass"}
    assert statuses(checks)["permissions: devices"] == "pass"
    assert passed(checks, strict=True)


def test_expired_and_expiring_tokens():
    now = int(datetime.now(UTC).timestamp())
    expired = validate_token(decode_token(make_jwt(graph_claims(exp=now - 10))))
    soon = validate_token(decode_token(make_jwt(graph_claims(exp=now + 120))))
    assert statuses(expired)["expiry"] == "fail"
    assert statuses(soon)["expiry"] == "warn"
    assert passed(soon)
    assert not passed(soon, strict=True)


def test_wrong_audience_tenant_and_issuer_fail():
    token = make_jwt(
        graph_claims(
            aud="https://management.azure.com/",
            tid=OTHER_TENANT,
            iss=f"https://sts.windows.net/{TENANT}/",
        )
    )
    result = statuses(validate_token(decode_token(token), resource=GRAPH, tenant_id=TENANT))
    assert result["audience"] == "fail"
    assert result["tenant"] == "fail"
    assert result["issuer"] == "fail"


def test_each_feature_the_token_cannot_serve_warns_and_required_ones_fail():
    token = decode_token(make_jwt(graph_claims(scp="Device.Read.All")))
    checks = validate_token(
        token, resource=GRAPH, required=["GroupMember.Read.All"], requirements=REQUIREMENTS
    )
    result = statuses(checks)
    assert result["permissions: devices"] == "pass"
    assert result["permissions: groups"] == "warn"
    assert result["permissions: policies"] == "warn"
    # Requirements for another API are not reported against a Graph token.
    assert "permissions: machines" not in result
    assert result["requires GroupMember.Read.All"] == "fail"
    assert not passed(checks)
    detail = next(check.detail for check in checks if check.name == "permissions: policies")
    assert detail == "needs one of Policy.Read.All"


def test_a_token_without_scp_or_roles_warns_once():
    token = decode_token(make_jwt(graph_claims(scp=None)))
    checks = validate_token(token, resource=GRAPH, requirements=REQUIREMENTS)
    assert [check.name for check in checks if "permissions" in check.name] == ["permissions"]
    assert statuses(checks)["permissions"] == "warn"


def test_user_impersonation_warns_that_access_rests_on_the_service_role():
    # What the Azure CLI gets for Defender: a delegated token with no granular scopes.
    claims = graph_claims(aud="https://api.securitycenter.microsoft.com", scp="user_impersonation")
    checks = validate_token(
        decode_token(make_jwt(claims)), resource=MDE, tenant_id=TENANT, requirements=REQUIREMENTS
    )
    permission = next(check for check in checks if check.name == "permissions")
    assert permission.status == "warn"
    assert "user_impersonation" in permission.detail


def test_an_mde_app_token_with_machine_read_all_passes():
    claims = graph_claims(
        aud="https://api.securitycenter.microsoft.com", roles=["Machine.Read.All"]
    )
    del claims["scp"], claims["upn"]
    decoded = decode_token(make_jwt(claims))
    assert decoded.identity_type == "app"
    checks = validate_token(decoded, resource=MDE, tenant_id=TENANT, requirements=REQUIREMENTS)
    assert set(statuses(checks).values()) == {"pass"}
    assert "permissions: machines" in statuses(checks)
