import pytest

from libre_devops_helpers.core import colour, picture

SQUARE = """\
# An orange square on blue, with a corner cut.
p #1E3A8A :
r #F97316 #
---
.ppp
prrp
prrp
pppp
"""


def test_a_picture_draws_two_rows_a_line_in_colour(monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    drawn = picture.parse(SQUARE).lines(coloured=True)
    assert len(drawn) == 2
    blue, orange = "\x1b[38;2;30;58;138m", "\x1b[38;2;249;115;22m"
    # A pixel under none is a lower half block.
    assert drawn[0].startswith(colour.style("▄", "#1E3A8A"))
    # Two colours in one cell: the upper in front, the lower behind it.
    assert f"{blue}\x1b[48;2;249;115;22m▀" in drawn[0]
    assert f"{orange}\x1b[48;2;30;58;138m▀" in drawn[1]
    # Two of one colour: a full block.
    assert f"{blue}█" in drawn[1]


def test_without_colour_a_picture_keeps_its_shape_in_its_own_characters():
    # Each line draws its upper pixel, else its lower one.
    assert picture.parse(SQUARE).lines(coloured=False) == ["::::", ":##:"]


def test_an_odd_last_row_is_drawn_alone_and_blank_pixels_are_nothing():
    art = "a #FFFFFF @\n---\na.\n.a\na.\n"
    shape = picture.parse(art)
    assert shape.width == 2
    assert shape.lines(coloured=False) == ["@@", "@"]
    blank = picture.parse("a #FFFFFF\n---\n..\n..\n")
    assert blank.lines(coloured=True) == [""]
    assert blank.characters == {"a": "a"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("p #1E3A8A\n..\n", "a palette, a line of ---"),
        ("p purple\n---\np\n", "not a palette entry"),
        ("p #1E3A8A\n---\n", "at least one row"),
        ("p #1E3A8A\n---\npp\np\n", r"as wide: found \[1, 2\]"),
        ("p #1E3A8A\n---\npq\n", "not in the palette: q"),
    ],
    ids=["no-separator", "bad-entry", "no-rows", "ragged", "unknown-pixel"],
)
def test_a_picture_that_cannot_be_read_says_why(text, message):
    with pytest.raises(ValueError, match=message):
        picture.parse(text)
