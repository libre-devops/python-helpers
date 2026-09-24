import json

import pytest

from fakes.http import fake_session, json_body, routes
from fakes.ids import SUBSCRIPTION, TENANT
from fakes.logicapps import ARM_RESOURCE, BARE, CODE_VIEW
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import ApiError, InputError, NotFoundError
from libre_devops_helpers.microsoft.logicapps import LogicAppsClient, parse

GROUP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-soc"
WORKFLOWS = f"{GROUP}/providers/Microsoft.Logic/workflows"
VALIDATE = f"{GROUP}/providers/Microsoft.Logic/locations/uksouth/workflows/router/validate"


def client(table):
    session, adapter = fake_session(routes(table))
    tokens = StaticTokens()
    return LogicAppsClient.create(tokens, TENANT, session=session), adapter, tokens


def test_workflows_are_listed_and_read_with_an_arm_token():
    api, adapter, tokens = client(
        {
            WORKFLOWS: (200, {"value": [{"name": "logic-arm"}]}),
            f"{WORKFLOWS}/logic-arm": (200, ARM_RESOURCE),
        }
    )
    assert [item["name"] for item in api.workflows(SUBSCRIPTION, "rg-soc")] == ["logic-arm"]
    assert api.workflow(SUBSCRIPTION, "rg-soc", "logic-arm")["name"] == "logic-arm"
    assert tokens.calls[0][0] == "https://management.azure.com/"
    assert "api-version=2019-05-01" in adapter.requests[0].url


def test_a_missing_workflow_is_not_found():
    api, _, _ = client({f"{WORKFLOWS}/gone": (404, {"error": {"code": "ResourceNotFound"}})})
    with pytest.raises(NotFoundError, match="no workflow 'gone'"):
        api.workflow(SUBSCRIPTION, "rg-soc", "gone")


def test_the_resource_groups_location_is_read():
    api, _, _ = client({GROUP: (200, {"location": "uksouth"})})
    assert api.location_of(SUBSCRIPTION, "rg-soc") == "uksouth"
    empty, _, _ = client({GROUP: (200, {})})
    with pytest.raises(ApiError, match="has no location"):
        empty.location_of(SUBSCRIPTION, "rg-soc")


def test_validation_posts_the_definition_with_its_values():
    api, adapter, _ = client({VALIDATE: (200, b"")})
    verdict = api.validate(
        parse(json.dumps(CODE_VIEW), default_name="router"),
        subscription=SUBSCRIPTION,
        resource_group="rg-soc",
        location="uksouth",
    )
    assert (verdict.valid, verdict.workflow, verdict.location) == (True, "router", "uksouth")
    body = json_body(adapter.requests[0])
    assert body["location"] == "uksouth"
    assert body["properties"]["definition"] == CODE_VIEW["definition"]
    assert body["properties"]["parameters"] == CODE_VIEW["parameters"]
    assert adapter.requests[0].method == "POST"


def test_a_rejected_definition_is_a_verdict_not_an_error():
    rejection = (
        400,
        {
            "error": {
                "code": "InvalidTemplate",
                "message": "The value for the workflow parameter 'x' is not provided",
            }
        },
    )
    api, adapter, _ = client({VALIDATE: rejection})
    verdict = api.validate(
        parse(json.dumps(BARE), default_name="router"),
        subscription=SUBSCRIPTION,
        resource_group="rg-soc",
        location="uksouth",
    )
    assert (verdict.valid, verdict.code) == (False, "InvalidTemplate")
    assert "is not provided" in verdict.message
    assert "parameters" not in json_body(adapter.requests[0])["properties"]


def test_other_failures_still_raise():
    api, _, _ = client({VALIDATE: (403, {"error": {"code": "AuthorizationFailed"}})})
    with pytest.raises(ApiError):
        api.validate(
            parse(json.dumps(BARE), default_name="router"),
            subscription=SUBSCRIPTION,
            resource_group="rg-soc",
            location="uksouth",
        )


@pytest.mark.parametrize(
    ("subscription", "group", "name", "location", "message"),
    [
        ("not-a-guid", "rg", "wf", "uksouth", "not a subscription id"),
        (SUBSCRIPTION, "rg/../other", "wf", "uksouth", "not a resource group name"),
        (SUBSCRIPTION, "rg", "wf/../x", "uksouth", "not a Logic App workflow name"),
        (SUBSCRIPTION, "rg", "wf", "UK South", "not an Azure region name"),
    ],
)
def test_names_are_checked_before_they_go_into_a_path(subscription, group, name, location, message):
    api, adapter, _ = client({})
    with pytest.raises(InputError, match=message):
        api.validate(
            parse(json.dumps(BARE)),
            subscription=subscription,
            resource_group=group,
            location=location,
            name=name,
        )
    assert adapter.requests == []
