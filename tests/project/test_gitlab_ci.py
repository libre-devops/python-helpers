"""The GitLab CI (.gitlab-ci.yml) against the GitHub workflows it mirrors.

Dependabot updates the GitHub workflows and the Containerfile, but not this file, so each
version pinned in both is checked to be the same here: a bump there fails this test until
it is made here too. And it publishes only to the project's own GitLab registries.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GITLAB = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_uv_is_the_containerfiles():
    containerfile = (ROOT / "Containerfile").read_text(encoding="utf-8")
    found = re.search(r"^FROM ghcr\.io/astral-sh/uv:(\S+)@", containerfile, re.MULTILINE)
    assert found is not None
    assert GITLAB["variables"]["UV_VERSION"] == found.group(1)


def test_the_scanners_are_the_github_workflows():
    ci, container = workflow("ci.yml")["env"], workflow("container.yml")["env"]
    variables = GITLAB["variables"]
    assert variables["PIP_AUDIT_VERSION"] == ci["PIP_AUDIT_VERSION"]
    assert f":v{ci['GITLEAKS_VERSION']}@sha256:" in variables["GITLEAKS_IMAGE"]
    for key in ("TRIVY_VERSION", "TRIVY_SHA256", "TRIVY_DB_REPOSITORY"):
        assert variables[key] == container[key], key


def test_every_python_github_tests_is_tested():
    matrix = workflow("ci.yml")["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    tested = set(GITLAB["test"]["parallel"]["matrix"][0]["PYTHON"])
    tested.add(GITLAB["variables"]["PYTHON"])  # the coverage job's
    assert tested == set(matrix)


def test_the_images_are_the_container_workflows():
    variants = workflow("container.yml")["jobs"]["image"]["strategy"]["matrix"]["include"]
    github = {item["variant"]: item["gate"] for item in variants}
    gitlab = {item["VARIANT"]: item["GATE"] for item in GITLAB["container"]["parallel"]["matrix"]}
    assert gitlab == github


def test_it_publishes_only_to_its_own_registries():
    text = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    for elsewhere in ("upload.pypi.org", "ghcr.io/libre-devops", "docker.io/libre"):
        assert elsewhere not in text
    for job in ("package", "release"):
        assert GITLAB[job]["rules"] == [{"if": "$CI_COMMIT_TAG =~ /^v\\d+\\.\\d+\\.\\d+/"}], job
    assert "CI_REGISTRY_IMAGE" in "\n".join(GITLAB["container"]["script"])


def test_the_package_job_does_not_ask_the_index_what_is_there():
    # GitLab redirects the index of a package it does not hold to pypi.org, so a check
    # there sees PyPI's files and skips the upload.
    package = GITLAB["package"]
    assert "UV_PUBLISH_CHECK_URL" not in package["variables"]
    lines = "\n".join(package["script"]).splitlines()
    commands = [line for line in lines if not line.lstrip().startswith("#")]
    assert not any("uv publish" in line and "--check-url" in line for line in commands)
