from libre_devops_helpers.servicenow.roles import RoleRequirement


def test_any_listed_role_or_admin_meets_a_requirement():
    requirement = RoleRequirement("security incidents", ("sn_si.analyst", "sn_si.manager"))
    assert requirement.met_by(["itil", "SN_SI.Analyst"])
    assert requirement.met_by(["admin"])
    assert not requirement.met_by(["itil"])
