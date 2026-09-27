import base64
import hashlib
import re
from datetime import UTC, datetime

from libre_devops_helpers.cli import html
from libre_devops_helpers.core import brand

WHEN = datetime(2026, 9, 27, 14, 12, tzinfo=UTC)


def a_page(**changes):
    options = {
        "heading": "devices check",
        "command": "ldo devices check -f plan.xlsx",
        "tables": [
            html.Table(
                ["DEVICE", "ENTRA", "DEFENDER"],
                [
                    ["web01", ("ok", "green"), ("ok", "green")],
                    ["web02", ("ok", "green"), ("not onboarded", "yellow")],
                    ["web03", ("not in Entra", "red"), ("-", "bright_black")],
                    ["<script>alert(1)</script>", "plain", ("", "red")],
                ],
            )
        ],
        "notes": [("note", "2/4 complete (profile az-active)"), ("warning", "rows hidden")],
        "generated": WHEN,
    }
    return html.page(**{**options, **changes})


def test_the_page_stands_alone_and_its_policy_admits_only_its_own_style_and_script():
    page = a_page()
    assert page.startswith("<!doctype html>")
    # Nothing is fetched: no src, no url() or @import, and one link, to the repository.
    assert " src=" not in page
    assert "url(" not in page
    assert "@import" not in page
    assert re.findall(r'href="([^"]+)"', page) == [brand.REPOSITORY]
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    policy = re.search(r'Content-Security-Policy" content="([^"]+)"', page).group(1)

    def digest(text):
        return base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()

    assert f"style-src 'sha256-{digest(style)}'" in policy
    assert f"script-src 'sha256-{digest(script)}'" in policy
    assert "default-src 'none'" in policy


def test_every_value_is_escaped():
    page = a_page(heading="<b>x</b>")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<h1>&lt;b&gt;x&lt;/b&gt;</h1>" in page


def test_colours_become_pills_and_rows_are_marked_by_their_worst():
    page = a_page()
    assert '<span class="pill ok">ok</span>' in page
    assert '<span class="pill warn">not onboarded</span>' in page
    assert '<span class="muted">-</span>' in page
    assert '<tr class="warn"><td>web02</td>' in page
    assert '<tr class="err"><td>web03</td>' in page
    assert "<tr><td>web01</td>" in page


def test_the_cards_count_rows_by_how_they_fared_and_the_notes_are_kept():
    page = a_page()
    assert '<div class="card "><b>4</b><span>rows</span></div>' in page
    assert '<div class="card ok"><b>1</b><span>ok</span></div>' in page
    assert '<div class="card warn"><b>1</b><span>attention</span></div>' in page
    assert '<div class="card err"><b>2</b><span>errors</span></div>' in page
    assert '<p class="note">2/4 complete (profile az-active)</p>' in page
    assert '<p class="warning">rows hidden</p>' in page
    assert "Written 2026-09-27 14:12 UTC by ldo" in page
    assert '<div class="notes">' not in a_page(notes=[])


def test_a_row_without_colours_has_no_status():
    assert html.row_status(["a", "b"]) == ""
    assert html.row_status(["a", ("x", None)]) == ""


def test_the_accent_is_the_brands_when_it_is_a_colour(monkeypatch):
    monkeypatch.setattr(brand, "ACCENT", "#0F766E")
    assert ":root{--accent:#0F766E}" in a_page()
    monkeypatch.setattr(brand, "ACCENT", "red;} body{display:none")
    assert ":root{--accent:#1E3A8A}" in a_page()
