import pytest

from fakes.detections import PATH, rule
from fakes.http import fake_session, routes
from fakes.ids import TENANT
from fakes.tokens import StaticTokens
from libre_devops_helpers.core.errors import AmbiguousError, ApiError, InputError, NotFoundError
from libre_devops_helpers.microsoft.detections import SCOPE_HINT, DetectionsClient


def client(table):
    session, adapter = fake_session(routes(table))
    return DetectionsClient.create(StaticTokens(), TENANT, session=session), adapter


def test_rules_follow_pages_and_come_back_by_name():
    next_link = f"https://graph.microsoft.com{PATH}?$skiptoken=2"

    def pages(request):
        if "skiptoken" in request.url:
            return (200, {"value": [rule("2", "web2 rule")]})
        return (200, {"value": [rule("10", "web10 rule")], "@odata.nextLink": next_link})

    detections, adapter = client({PATH: pages})
    assert [found.display_name for found in detections.rules()] == ["web2 rule", "web10 rule"]
    assert adapter.requests[0].url.startswith("https://graph.microsoft.com/beta/")


def test_one_rule_by_id_or_by_name_whatever_the_case():
    detections, _ = client(
        {
            f"{PATH}/7506": (200, rule()),
            PATH: (200, {"value": [rule(), rule("8", "Other")]}),
        }
    )
    assert detections.rule("7506").id == "7506"
    assert detections.rule("certutil USED to download remote content").id == "7506"
    with pytest.raises(NotFoundError, match="no custom detection rule is named 'nope'"):
        detections.rule("nope")
    with pytest.raises(InputError, match="no rule named"):
        detections.rule("  ")


def test_a_shared_name_asks_for_the_id_and_a_missing_id_is_not_found():
    detections, _ = client(
        {
            PATH: (200, {"value": [rule("1", "Same"), rule("2", "Same")]}),
            f"{PATH}/99": (404, {"error": {"code": "NotFound"}}),
        }
    )
    with pytest.raises(AmbiguousError, match="2 rules are named 'same': 1, 2"):
        detections.rule("same")
    with pytest.raises(NotFoundError, match="no custom detection rule has id 99"):
        detections.rule("99")


def test_a_refusal_says_which_scope_and_how_the_azure_cli_can_have_it():
    detections, _ = client({PATH: (403, {"error": {"code": "Forbidden", "message": "denied"}})})
    with pytest.raises(ApiError) as caught:
        detections.rules()
    assert caught.value.hint == SCOPE_HINT
    assert "04b07795-8ddb-461a-bbee-02f9e1bf7b46" in SCOPE_HINT
