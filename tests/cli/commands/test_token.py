import json

from fakes.ids import CLIENT_ID, TENANT
from fakes.tenant import runner, runtime
from fakes.tokens import graph_claims, make_jwt
from libre_devops_helpers.cli import app
from libre_devops_helpers.core.token_store import MemoryStore


def test_token_checks_pass_and_raw_prints_only_the_token(profiles_config):
    result = runner.invoke(
        app, ["entra", "token", "graph", "-o", "json"], obj=runtime(profiles_config)
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["valid"]
    assert report["claims"]["tid"] == TENANT

    raw = runner.invoke(app, ["entra", "token", "graph", "--raw"], obj=runtime(profiles_config))
    assert raw.exit_code == 0
    assert raw.stdout.strip().count(".") == 2


def test_token_for_the_wrong_tenant_fails(profiles_config):
    # az hands back a TENANT token, but test-tenant expects OTHER_TENANT.
    result = runner.invoke(
        app, ["entra", "token", "graph", "-p", "test-tenant"], obj=runtime(profiles_config)
    )
    assert result.exit_code == 1
    assert "FAIL" in result.stdout


def test_inspect_token_reads_stdin():
    token = make_jwt(graph_claims())
    result = runner.invoke(
        app, ["entra", "inspect-token", "--resource", "graph", "--tenant", TENANT], input=token
    )
    assert result.exit_code == 0, result.output
    assert "analyst@example.com" in result.stdout
    assert token not in result.stdout


def test_inspect_token_rejects_empty_stdin():
    result = runner.invoke(app, ["entra", "inspect-token"], input="")
    assert result.exit_code == 1
    assert "no token on stdin" in str(result.exception)


def delegated_config(tmp_path, token_cache: str):
    path = tmp_path / f"delegated-{token_cache}.toml"
    path.write_text(
        f"""
[microsoft]
default_profile = "pim"

[microsoft.profiles.pim]
tenant_id = "{TENANT}"
auth = "interactive"
client_id = "{CLIENT_ID}"
token_cache = "{token_cache}"
""",
        encoding="utf-8",
    )
    return path


def test_sign_out_forgets_a_kept_sign_in(tmp_path):
    store = MemoryStore()
    store.save(f"login.microsoftonline.com|{CLIENT_ID}|{TENANT}", "refresh")
    obj = runtime(delegated_config(tmp_path, "keychain"))
    obj.token_store = store
    result = runner.invoke(app, ["entra", "sign-out"], obj=obj)
    assert result.exit_code == 0, result.output
    assert "Forgot the sign-in kept for pim (keychain)" in result.stderr
    again = runner.invoke(app, ["entra", "sign-out"], obj=obj)
    assert "No sign-in was kept for pim" in again.stderr


def test_sign_out_with_nothing_kept_or_an_azure_cli_profile_says_so(tmp_path, profiles_config):
    memory = runner.invoke(
        app, ["entra", "sign-out"], obj=runtime(delegated_config(tmp_path, "memory"))
    )
    assert memory.exit_code == 0, memory.output
    assert "keeps no sign-in" in memory.stderr
    cli = runner.invoke(app, ["entra", "sign-out"], obj=runtime(profiles_config))
    assert "az logout" in (cli.exception.hint or "")
