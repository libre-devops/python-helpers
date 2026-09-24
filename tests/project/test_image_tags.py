import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "image_tags.py"
spec = importlib.util.spec_from_file_location("image_tags", SCRIPT)
image_tags = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image_tags)


def test_the_default_image_gets_exact_floating_latest_and_stamped_tags():
    assert image_tags.image_tags("1.4.2", stamp="20260924.57", latest=True) == [
        "1.4.2",
        "1.4",
        "1",
        "latest",
        "1.4.2-20260924.57",
    ]


def test_the_slim_variant_carries_a_suffix():
    assert image_tags.image_tags("1.4.2", "tool", stamp="20260924", latest=True) == [
        "1.4.2-slim",
        "1.4-slim",
        "1-slim",
        "slim",
        "1.4.2-slim-20260924",
    ]


def test_before_1_0_there_is_no_major_tag():
    assert image_tags.image_tags("0.3.1", latest=True) == ["0.3.1", "0.3", "latest"]


def test_an_older_release_does_not_take_latest():
    assert image_tags.image_tags("1.3.9") == ["1.3.9", "1.3", "1"]


def test_a_pre_release_gets_only_its_own_tags():
    assert image_tags.image_tags("2.0.0rc1", stamp="20260924", latest=True) == [
        "2.0.0rc1",
        "2.0.0rc1-20260924",
    ]


@pytest.mark.parametrize(
    ("version", "options", "message"),
    [
        ("1.0.0+local", {}, "cannot be used in an image tag"),
        ("1.0.0", {"variant": "full"}, "unknown variant"),
        ("1.0.0", {"stamp": "yesterday"}, "must be a date"),
        ("1" * 130, {}, "longer than 128"),
    ],
)
def test_bad_input_is_refused(version, options, message):
    with pytest.raises(ValueError, match=message):
        image_tags.image_tags(version, **options)


def test_the_command_prints_one_image_reference_per_line(capsys):
    args = ["--version", "0.2.0", "--variant", "tool", "--latest", "--image", "ghcr.io/o/r"]
    assert image_tags.main(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "ghcr.io/o/r:0.2.0-slim",
        "ghcr.io/o/r:0.2-slim",
        "ghcr.io/o/r:slim",
    ]


def test_the_command_reports_bad_input_as_usage(capsys):
    with pytest.raises(SystemExit) as caught:
        image_tags.main(["--version", "bad version"])
    assert caught.value.code == 2
    assert "cannot be used in an image tag" in capsys.readouterr().err
