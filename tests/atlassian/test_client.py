import pytest

from fakes.atlassian import EMAIL, ENV, SITE, FakeSite
from fakes.http import fake_session
from libre_devops_helpers.atlassian import ApiToken, AtlassianServiceClient, Profile, token_for
from libre_devops_helpers.core.errors import ApiError, AuthError

PROFILE = Profile("work", SITE, EMAIL)


def test_the_token_goes_with_the_email_and_is_never_shown():
    credential = token_for(PROFILE, ENV)
    assert "atl-token" not in repr(credential)
    assert repr(credential) == "ApiToken(email='ana@example.com')"
    with pytest.raises(AuthError, match="no Atlassian API token in JIRA_TOKEN") as error:
        token_for(PROFILE, {})
    assert "id.atlassian.com" in error.value.hint
    for email, token in (("", "t"), ("a@example.com", "")):
        with pytest.raises(AuthError):
            ApiToken(email, token)


def test_a_wrong_token_is_refused_with_what_to_check():
    session, _ = fake_session(FakeSite())
    client = AtlassianServiceClient.create(SITE, ApiToken(EMAIL, "wrong"), session=session)
    with pytest.raises(ApiError) as error:
        client.api.get("/rest/api/3/myself")
    assert "Client must be authenticated" in str(error.value)
    assert "email" in error.value.hint
    client.close()


def test_a_profile_makes_a_client_for_its_site():
    session, _ = fake_session(FakeSite())
    with AtlassianServiceClient.for_profile(PROFILE, ENV, session=session) as client:
        assert client.api.get("/rest/api/3/myself")["displayName"] == "Ana"
