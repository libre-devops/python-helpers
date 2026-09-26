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


def test_packages_install_from_the_index_by_the_locks_hashes_and_the_login_is_a_secret():
    # Behind a package proxy the image builds from PACKAGE_INDEX, each package checked
    # against uv.lock's hash; the index's login is a build secret, never a build argument,
    # which the image's history would keep.
    text = CONTAINERFILE.read_text()
    assert "ARG PACKAGE_INDEX=https://pypi.org/simple" in text
    assert "uv sync --locked" not in text
    installs = [line for line in text.splitlines() if "uv pip install" in line]
    assert len(installs) == 3
    assert text.count("--require-hashes") == 2  # the project itself has no hash to check
    assert text.count("--mount=type=secret,id=netrc,target=/root/.netrc") == 3
    assert not re.search(r"ARG \w*(TOKEN|PASSWORD|NETRC|SECRET)", text, re.IGNORECASE)


def test_an_index_behind_its_own_authority_is_trusted_through_a_bundle_for_the_build_alone():
    # Every step that installs can be given the organisation's certificate bundle, as a
    # secret so no layer keeps it, and uses it only when one was given.
    text = CONTAINERFILE.read_text()
    bundle = "/run/secrets/ca-bundle"
    assert text.count(f"--mount=type=secret,id=ca-bundle,target={bundle}") == 3
    assert text.count(f"if [ -s {bundle} ]; then export SSL_CERT_FILE={bundle}; fi") == 3
    assert "ENV SSL_CERT_FILE" not in text


def test_the_debian_upgrade_can_be_left_out_where_the_mirrors_cannot_be_reached():
    text = CONTAINERFILE.read_text()
    assert "ARG DEBIAN_UPGRADE=true" in text
    assert 'if [ "$DEBIAN_UPGRADE" = true ]; then' in text
