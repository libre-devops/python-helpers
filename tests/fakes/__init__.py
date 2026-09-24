"""Shared test fakes, one module per concern.

Nothing in the suite touches the network, a real Azure CLI or a real clock: tests import
what they need from here, for example ``from fakes.http import fake_session``.
"""
