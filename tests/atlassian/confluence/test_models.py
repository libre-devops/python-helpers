from fakes.atlassian import SITE, page
from libre_devops_helpers.atlassian.confluence import Page, SearchHit, Space


def test_the_records_read_their_fields_and_tolerate_missing_ones():
    found = Page.from_api(page("5", "Runbook"), SITE)
    assert (found.version, found.url.endswith("/pages/5/Runbook")) == (3, True)
    bare = Page.from_api({"id": "6"}, SITE)
    assert (bare.version, bare.url, bare.updated) == (0, "", None)
    assert Space.from_api({"id": "1", "key": "OPS"}, SITE).url == ""
    hit = SearchHit.from_api({"entityType": "space", "title": "Ops"}, SITE)
    assert (hit.type, hit.url) == ("space", "")
