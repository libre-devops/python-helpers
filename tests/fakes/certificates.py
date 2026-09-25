"""A test CA's certificate, standing in for a TLS-inspecting proxy's root.

Made once with openssl for these tests; its key was thrown away, so it can sign nothing.
It is not among the public roots, which is the point.
"""

TEST_CA = """\
-----BEGIN CERTIFICATE-----
MIIB4DCCAYWgAwIBAgIULUUDMXXfXRwutyBuzgStx1KIiQQwCgYIKoZIzj0EAwIw
PDEjMCEGA1UEAwwaQ29udG9zbyBUZXN0IEluc3BlY3Rpb24gQ0ExFTATBgNVBAoM
DENvbnRvc28gVGVzdDAgFw0yNjA5MjUwNzU3NDFaGA8yMTI2MDkwMTA3NTc0MVow
PDEjMCEGA1UEAwwaQ29udG9zbyBUZXN0IEluc3BlY3Rpb24gQ0ExFTATBgNVBAoM
DENvbnRvc28gVGVzdDBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABIZU99OwjyhR
S99rXH21Ve+ixPBqVSx9RpVipVPqypIfJ/etKP8KdmBJ2oRiGjOz0ZvUZXEst8vg
6lUPHgB/PrajYzBhMB0GA1UdDgQWBBSl1mOPPVGrRSKCHdlZLxbzE3GO6zAfBgNV
HSMEGDAWgBSl1mOPPVGrRSKCHdlZLxbzE3GO6zAPBgNVHRMBAf8EBTADAQH/MA4G
A1UdDwEB/wQEAwIBBjAKBggqhkjOPQQDAgNJADBGAiEA7h8TbwnAjWSB2+mzGPBV
zWfsaZxAenewtDk6W435kC8CIQD8bBIfBo7ljnp11CUUlRgZRtRc7OzATs27agz8
2Xlm1Q==
-----END CERTIFICATE-----
"""

# Not a certificate OpenSSL can load: the shape of one, with rubbish inside.
BROKEN = "-----BEGIN CERTIFICATE-----\nbm90IGEgY2VydGlmaWNhdGU=\n-----END CERTIFICATE-----\n"
