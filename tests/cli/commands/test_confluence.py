import json

from fakes.atlassian import ENV, FakeSite
from fakes.tenant import run


def confluence(config_file, *args):
    return run(config_file, FakeSite(), ["confluence", *args], environ=ENV)


def test_spaces_and_their_pages(config_file):
    spaces = confluence(config_file, "spaces", "-o", "csv").stdout.splitlines()
    assert spaces[1].startswith("OPS,Operations,global,current,")
    pages = confluence(config_file, "pages", "--space", "OPS", "-o", "csv").stdout.splitlines()
    assert pages[0] == "ID,TITLE,SPACE,VERSION,UPDATED,LINK"
    assert pages[1].startswith("101,Runbook,OPS,3,")
    everywhere = json.loads(confluence(config_file, "pages", "-o", "json").stdout)
    assert {page["space"] for page in everywhere} == {"OPS", "~acc1"}


def test_a_page_is_its_details_then_its_body_or_only_its_markdown(config_file):
    result = confluence(config_file, "page", "101")
    assert result.exit_code == 0, result.output
    assert "Title    Runbook" in result.stdout
    assert result.stdout.rstrip().endswith("## Restart\n\nRun `systemctl restart app`.")
    assert confluence(config_file, "page", "101", "--markdown").stdout.startswith("## Restart")
    record = json.loads(confluence(config_file, "page", "101", "-o", "json").stdout)
    assert (record["title"], record["body"]) == (
        "Runbook",
        "## Restart\n\nRun `systemctl restart app`.",
    )


def test_search_finds_pages_by_cql(config_file):
    result = confluence(config_file, "search", 'type = page AND text ~ "restart"', "-o", "csv")
    assert result.stdout.splitlines()[1].startswith("page,Runbook,Operations,")
