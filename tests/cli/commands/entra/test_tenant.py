from fakes.tenant import invoke


def test_app_credentials_exits_3_when_one_is_expiring(config_file, tenant):
    result = invoke(config_file, tenant, ["entra", "app-credentials", "-o", "csv"])
    assert result.exit_code == 3, result.output
    header, row = result.stdout.splitlines()
    assert header.startswith("APP,KIND,CREDENTIAL")
    assert row.startswith("billing-api,secret,ci,")


def test_an_empty_ca_policy_list_warns_that_the_token_may_be_why(config_file, tenant):
    result = invoke(config_file, tenant, ["entra", "ca-policies"])
    assert result.exit_code == 0, result.output
    assert "may lack Policy.Read.All" in result.stderr
