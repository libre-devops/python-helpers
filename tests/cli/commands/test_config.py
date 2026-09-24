import os

from fakes.tenant import runner
from libre_devops_helpers.cli import app


def test_config_init_writes_the_template_once(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    result = runner.invoke(app, ["--config", str(path), "config", "init"])
    assert result.exit_code == 0, result.output
    assert "[microsoft.profiles.test-tenant]" in path.read_text()
    again = runner.invoke(app, ["--config", str(path), "config", "init"])
    assert "already exists" in str(again.exception)
    path.chmod(0o644)
    forced = runner.invoke(app, ["--config", str(path), "config", "init", "--force"])
    assert forced.exit_code == 0
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
