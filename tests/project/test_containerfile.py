import re
from pathlib import Path

CONTAINERFILE = Path(__file__).resolve().parents[2] / "Containerfile"
FROM = re.compile(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", re.MULTILINE)


def stages() -> dict[str, str]:
    return {name: image for image, name in FROM.findall(CONTAINERFILE.read_text())}


def test_every_python_stage_is_one_pinned_base():
    # The Azure CLI's bytecode is compiled in one stage and run in another, so the two must
    # be the same Python; a partial base image bump would break that quietly.
    pythons = {image for image in stages().values() if "library/python:" in image}
    assert len(pythons) == 1, pythons
    assert "@sha256:" in pythons.pop()


def test_the_azure_cli_is_compiled_on_the_build_platform_and_shipped_compiled():
    text = CONTAINERFILE.read_text()
    assert "FROM --platform=$BUILDPLATFORM" in text
    assert "COPY --from=compile-az /opt/az /opt/az" in text
    assert (
        "COPY --from=build-az /opt/az /opt/az"
        in text.split("AS compile-az", 1)[1].split("\nFROM", 1)[0]
    )
