import pytest

from fakes.tenant import CONFIG, PROFILES_CONFIG, Tenant


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def tenant():
    return Tenant()


@pytest.fixture
def profiles_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(PROFILES_CONFIG, encoding="utf-8")
    return path
