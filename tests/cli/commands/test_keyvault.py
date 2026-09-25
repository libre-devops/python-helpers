import json

from fakes.http import routes
from fakes.tenant import invoke, run, usage_error


def test_keyvault_expiry_reads_the_vaults_named_in_a_file(config_file, tenant, tmp_path):
    listed = tmp_path / "vaults.txt"
    listed.write_text("kv-app\nKV-APP\n", encoding="utf-8")
    result = invoke(config_file, tenant, ["keyvault", "expiry", "-f", str(listed), "-o", "json"])
    assert result.exit_code == 3, result.output
    items = json.loads(result.stdout)
    assert [(item["vault"], item["name"], item["days_left"]) for item in items] == [
        ("kv-app", "db", 4)
    ]
    assert "checked in 1 of 1 vault(s)" in result.stderr  # named twice, read once


def test_there_is_no_way_to_sweep_every_vault(config_file):
    # A request to every vault in the tenant is refused and logged by each one the person
    # cannot read, which looks like reconnaissance: vaults are only ever named.
    result = run(config_file, routes({}), ["keyvault", "expiry", "--all-vaults"])
    assert result.exit_code == 2
    assert "No such option: --all-vaults" in usage_error(result)


def test_a_named_vault_with_nothing_expiring_exits_0(config_file):
    handler = routes({"/secrets": (200, {"value": []}), "/certificates": (200, {"value": []})})
    args = ["keyvault", "expiry", "kv-app", "--kind", "secret", "--kind", "certificate"]
    result = run(config_file, handler, args)
    assert result.exit_code == 0, result.output
    summary = "0 item(s) expire within 30d (0 checked in 1 of 1 vault(s))"
    assert summary in result.stderr.splitlines()


def test_an_unreadable_vault_is_a_warning_and_exit_1(config_file):
    denied = (
        403,
        {"error": {"code": "Forbidden", "message": "Client address is not authorized"}},
    )
    result = run(
        config_file,
        routes({"/secrets": denied}),
        ["keyvault", "expiry", "kv-app", "--kind", "secret"],
    )
    assert result.exit_code == 1, result.output
    assert "cannot read vault kv-app" in result.stderr
    assert "hint:" in result.stderr
    assert "(0 checked in 0 of 1 vault(s))" in result.stderr
    assert "none of the 1 vault(s) could be read: see why above" in result.stderr


def test_expiry_needs_a_vault_and_a_known_kind(config_file):
    result = run(config_file, routes({}), ["keyvault", "expiry"])
    assert "no vaults given" in str(result.exception)
    result = run(config_file, routes({}), ["keyvault", "expiry", "kv-app", "--kind", "passwords"])
    assert result.exit_code == 2
    assert "--kind must be one of" in usage_error(result)
