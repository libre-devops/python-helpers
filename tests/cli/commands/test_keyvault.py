import json

from fakes.http import routes
from fakes.tenant import invoke, run


def test_keyvault_expiry_finds_vaults_through_resource_graph(config_file, tenant):
    result = invoke(config_file, tenant, ["keyvault", "expiry", "--all-vaults", "-o", "json"])
    assert result.exit_code == 3, result.output
    items = json.loads(result.stdout)
    assert [(item["vault"], item["name"], item["days_left"]) for item in items] == [
        ("kv-app", "db", 4)
    ]


def test_a_named_vault_with_nothing_expiring_exits_0(config_file):
    handler = routes({"/secrets": (200, {"value": []}), "/certificates": (200, {"value": []})})
    args = ["keyvault", "expiry", "kv-app", "--kind", "secret", "--kind", "certificate"]
    result = run(config_file, handler, args)
    assert result.exit_code == 0, result.output
    assert "0 item(s) expire within 30d 00h (0 checked in 1 vault(s))" in result.stderr


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


def test_expiry_needs_a_vault_and_a_known_kind(config_file):
    result = run(config_file, routes({}), ["keyvault", "expiry"])
    assert "no vaults given" in str(result.exception)
    result = run(config_file, routes({}), ["keyvault", "expiry", "kv-app", "--kind", "passwords"])
    assert result.exit_code == 2
    assert "--kind must be one of" in result.output
