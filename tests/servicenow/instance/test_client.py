import pytest

from fakes.http import fake_session
from fakes.servicenow import BUILD_TAG, INSTANCE, PASSWORD, USER_ID, USERNAME, FakeInstance
from libre_devops_helpers.core.errors import NotFoundError
from libre_devops_helpers.servicenow.auth import BasicCredential
from libre_devops_helpers.servicenow.instance import InstanceClient, Release
from libre_devops_helpers.servicenow.tables import TableClient


def client(instance: FakeInstance) -> InstanceClient:
    session, _ = fake_session(instance)
    credential = BasicCredential(USERNAME, PASSWORD)
    return InstanceClient(
        TableClient.create(INSTANCE, credential.authorization, scheme="Basic", session=session)
    )


def test_the_current_user_is_whoever_the_request_signs_in_as():
    instance = FakeInstance()
    user = client(instance).current_user()
    assert (user.sys_id, user.user_name, user.active, user.locked_out) == (
        USER_ID,
        "ana",
        True,
        False,
    )
    assert "javascript%3Ags.getUserID%28%29" in instance.requests[0].url


def test_a_named_user_must_exist():
    with pytest.raises(NotFoundError, match="named 'bob'"):
        client(FakeInstance()).current_user("bob")


def test_roles_are_the_active_ones_sorted():
    tables = client(FakeInstance())
    assert tables.roles(tables.current_user()) == ("admin", "itil")


def test_the_release_comes_from_glide_war_or_the_build_tag():
    instance = FakeInstance()
    release = client(instance).release()
    assert (release.family, release.patch, release.label) == ("Zurich", "patch10", "Zurich patch10")
    instance.tables["sys_properties"].append({"name": "glide.buildtag.last", "value": BUILD_TAG})
    assert client(instance).release().label == "Yokohama patch4"  # the build tag wins
    instance.tables["sys_properties"] = []
    assert client(instance).release() is None
    instance.denied.add("sys_properties")
    assert client(instance).release() is None


def test_an_unrecognised_build_tag_is_kept_as_it_is():
    assert Release.from_build_tag("custom-build").label == "custom-build"
    assert Release.from_build_tag("").label == "unknown"


def test_applications_are_listed_active_first_and_searched():
    tables = client(FakeInstance())
    assert [(app.name, app.kind) for app in tables.applications()] == [
        ("Vulnerability Response", "store app")
    ]
    every = tables.applications(active_only=False)
    assert [(app.scope, app.active) for app in every] == [("sn_vul", True), ("x_acme_tools", False)]
    assert [app.scope for app in tables.applications("acme", active_only=False)] == ["x_acme_tools"]


def test_security_incident_response_is_installed_when_its_table_is_there():
    instance = FakeInstance()
    status = client(instance).security_incident_response()
    assert not status.installed
    assert "sn_si_incident" in status.detail
    instance.tables["sys_db_object"].append({"name": "sn_si_incident"})
    assert client(instance).security_incident_response().installed
    instance.tables["sys_scope"].append(
        {
            "scope": "sn_si",
            "name": "Security Incident Response",
            "active": "true",
            "version": "21.2",
        }
    )
    status = client(instance).security_incident_response()
    assert (status.installed, status.version) == (True, "21.2")
