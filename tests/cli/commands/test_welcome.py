from fakes.tenant import runner, runtime
from libre_devops_helpers.cli import app
from libre_devops_helpers.core import brand


def test_welcome_without_a_config_points_to_config_init(tmp_path):
    result = runner.invoke(app, ["welcome"], obj=runtime(tmp_path / "config.toml"))
    assert result.exit_code == 0, result.output
    assert brand.DISPLAY_NAME in result.stderr  # the banner is forced, on stderr
    assert "(not created yet)" in result.stdout
    assert f"{brand.COMMAND} config init" in result.stdout


def test_welcome_with_a_config_points_to_the_next_steps(config_file):
    result = runner.invoke(app, ["welcome"], obj=runtime(config_file))
    assert result.exit_code == 0, result.output
    assert "(not created yet)" not in result.stdout
    assert f"{brand.COMMAND} profiles" in result.stdout
    assert f"{brand.COMMAND} devices check --help" in result.stdout
