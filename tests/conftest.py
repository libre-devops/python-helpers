"""Settings for the whole suite."""

import pytest

from libre_devops_helpers.core.token_store import FILE_ENV


@pytest.fixture(autouse=True)
def private_token_cache(tmp_path_factory, monkeypatch):
    """Point the kept sign-in file at a temporary folder, so no test writes to your home."""
    folder = tmp_path_factory.mktemp("token-cache")
    monkeypatch.setenv(FILE_ENV, str(folder / "refresh-tokens.json"))
