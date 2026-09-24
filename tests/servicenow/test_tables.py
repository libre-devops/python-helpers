import pytest

from fakes.http import fake_session
from fakes.servicenow import INSTANCE, PASSWORD, USERNAME, FakeInstance
from libre_devops_helpers.core.errors import ApiError, InputError
from libre_devops_helpers.servicenow import tables as tables_module
from libre_devops_helpers.servicenow.auth import BasicCredential
from libre_devops_helpers.servicenow.tables import TableClient, condition


def client(instance: FakeInstance) -> TableClient:
    session, _ = fake_session(instance)
    credential = BasicCredential(USERNAME, PASSWORD)
    return TableClient.create(INSTANCE, credential.authorization, scheme="Basic", session=session)


def test_records_are_read_with_the_query_and_fields_asked_for():
    instance = FakeInstance()
    rows = client(instance).records("sys_user", query="user_name=ana", fields=("user_name",))
    assert rows == [{"user_name": "ana"}]
    request = instance.requests[0]
    assert request.headers["Authorization"].startswith("Basic ")
    assert "sysparm_exclude_reference_link=true" in request.url


def test_records_are_paged_until_a_short_page_or_the_limit(monkeypatch):
    instance = FakeInstance()
    instance.tables["incident"] = [{"number": f"INC{n:04}"} for n in range(7)]
    monkeypatch.setattr(tables_module, "PAGE_SIZE", 3)
    assert len(client(instance).records("incident")) == 7
    assert len(instance.requests) == 3
    assert len(client(instance).records("incident", limit=4)) == 4


def test_first_is_the_first_match_or_none():
    tables = client(FakeInstance())
    assert tables.first("sys_user", query="user_name=ana")["name"] == "Ana Analyst"
    assert tables.first("sys_user", query="user_name=nobody") is None


@pytest.mark.parametrize(
    ("setup", "hint"),
    [
        (lambda i: setattr(i, "basic_allowed", False), "snc_basic_auth_api_access"),
        (lambda i: i.denied.add("sys_user"), "lacks a role"),
        (lambda i: i.tables.pop("sys_user"), "plugin or app is not installed"),
        (lambda i: setattr(i, "hibernating", True), "hibernating"),
    ],
)
def test_the_instance_saying_no_comes_with_a_hint(setup, hint):
    instance = FakeInstance()
    setup(instance)
    with pytest.raises(ApiError) as caught:
        client(instance).records("sys_user")
    assert hint in (caught.value.hint or "")


def test_a_condition_refuses_a_value_that_would_add_conditions():
    assert condition("name", "web01") == "name=web01"
    assert condition("name", "web", "LIKE") == "nameLIKEweb"
    with pytest.raises(InputError, match="cannot be used"):
        condition("name", "web01^ORactive=true")
