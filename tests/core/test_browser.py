import sys
import webbrowser

from libre_devops_helpers.core.browser import can_launch_browser


def test_a_browser_is_found_the_way_the_azure_cli_looks_for_one(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert can_launch_browser()
    monkeypatch.setattr(sys, "platform", "linux")

    def no_browser():
        raise webbrowser.Error("could not locate runnable browser")

    monkeypatch.setattr(webbrowser, "get", no_browser)
    assert not can_launch_browser()
    monkeypatch.setattr(webbrowser, "get", lambda: object())
    assert can_launch_browser()
