import logging
import sys
import webbrowser

from libre_devops_helpers.core.browser import can_launch_browser, open_quietly


def test_a_browser_is_found_the_way_the_azure_cli_looks_for_one(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert can_launch_browser()
    monkeypatch.setattr(sys, "platform", "linux")

    def no_browser():
        raise webbrowser.Error("could not locate runnable browser")

    monkeypatch.setattr(webbrowser, "get", no_browser)
    assert not can_launch_browser()
    monkeypatch.setattr(webbrowser, "get", object)
    assert can_launch_browser()


def test_a_browser_that_will_not_open_never_stops_a_sign_in(caplog):
    opened: list[str] = []
    open_quietly(opened.append, "https://login.example.com/x")
    assert opened == ["https://login.example.com/x"]

    def broken(url):
        raise OSError("no display")

    with caplog.at_level(logging.DEBUG):
        open_quietly(broken, "https://login.example.com/x")
    assert "could not open a browser" in caplog.text
