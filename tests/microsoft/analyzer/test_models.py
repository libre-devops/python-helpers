from libre_devops_helpers.microsoft.analyzer import AnalyzerReport, Fact, Finding


def test_a_finding_ranks_by_its_severity_and_an_unknown_one_comes_last():
    ranks = [
        Finding("1", level, "c", "k", "r").rank
        for level in ("error", "warning", "informational", "odd")
    ]
    assert ranks == [0, 1, 2, 3]


def test_a_report_finds_a_fact_by_name_and_counts_by_severity():
    report = AnalyzerReport(
        source="r.zip",
        platform="windows",
        host="web01",
        facts=(Fact("Device", "OS Name", "Windows"),),
        findings=(Finding("1", "warning", "c", "k", "r"), Finding("2", "warning", "c", "k", "r")),
    )
    assert report.fact("os name") == "Windows"
    assert report.fact("missing") == ""
    assert (report.count("warning"), report.count("error")) == (2, 0)
