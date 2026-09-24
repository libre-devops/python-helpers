import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")


def test_dpapi_round_trips_and_hides_the_data():
    from libre_devops_helpers.core import dpapi

    sealed = dpapi.protect(b"refresh-token")
    assert b"refresh-token" not in sealed
    assert dpapi.unprotect(sealed) == b"refresh-token"


def test_dpapi_refuses_data_it_did_not_seal():
    from libre_devops_helpers.core import dpapi

    # Which Windows error it is (invalid data, or a bad parameter) varies by version.
    with pytest.raises(OSError) as caught:  # noqa: PT011
        dpapi.unprotect(b"not sealed by DPAPI")
    assert caught.value.winerror is not None
