import pytest

from libre_devops_helpers.core.markdown import html_to_markdown


@pytest.mark.parametrize(
    ("html", "markdown"),
    [
        ("<h1>Runbook</h1><h3>Steps</h3>", "# Runbook\n\n### Steps"),
        (
            "<p>Use <strong>care</strong>, <em>read</em> and <code>ls</code>.</p>",
            "Use **care**, _read_ and `ls`.",
        ),
        (
            '<p>See <a href="https://a.example/x">the docs</a> or <a href="https://b.example">https://b.example</a></p>',
            "See [the docs](https://a.example/x) or https://b.example",
        ),
        (
            "<ul><li><p>one</p></li><li>two<ul><li>nested</li></ul></li></ul>",
            "- one\n- two\n  - nested",
        ),
        ("<ol><li>first</li><li>second</li></ol>", "1. first\n2. second"),
        (
            "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>x | y</td></tr></table>",
            "| A | B |\n| --- | --- |\n| 1 | x \\| y |",
        ),
        (
            "<table><tr><td><h2>Card</h2><p>text</p><ul><li>a</li><li>b</li></ul></td></tr></table>",
            "| Card text - a - b |\n| --- |",
        ),
        ("<pre>keep   this\n  as is</pre>", "```\nkeep   this\n  as is\n```"),
        (
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">bash</ac:parameter>'
            "<ac:plain-text-body><![CDATA[echo  hi]]></ac:plain-text-body></ac:structured-macro>",
            "```\necho  hi\n```",
        ),
        (
            "<ac:task-list><ac:task><ac:task-body>call</ac:task-body></ac:task></ac:task-list>",
            "- [ ] call",
        ),
        (
            "<blockquote>quoted</blockquote><p>a<br/>b</p><hr/><p>&lt;x&gt; &amp; y</p>",
            "> quoted\n\na  \nb\n\n---\n\n<x> & y",
        ),
        (
            '<p><img alt="diagram"/><img/> <span>kept</span> <script>no()</script></p>',
            "[diagram] kept",
        ),
        ("<p>unclosed <a href='https://c.example'>link", "unclosed link"),  # its text is kept
    ],
    ids=[
        "headings",
        "emphasis",
        "links",
        "lists",
        "ordered",
        "table",
        "layout-cell",
        "pre",
        "code-macro",
        "tasks",
        "quote-break-rule",
        "images-and-hidden",
        "unclosed",
    ],
)
def test_html_becomes_markdown(html, markdown):
    assert html_to_markdown(html) == markdown + "\n"


def test_a_list_item_outside_a_list_is_still_a_bullet():
    assert html_to_markdown("<li>alone</li>") == "- alone\n"
