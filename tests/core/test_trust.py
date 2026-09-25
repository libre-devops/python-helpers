import ssl
import subprocess
from pathlib import Path

import pytest
import requests.certs

from fakes.certificates import BROKEN, TEST_CA
from libre_devops_helpers.core import trust
from libre_devops_helpers.core.errors import ConfigError

PUBLIC = trust.split_pem(Path(requests.certs.where()).read_text(encoding="utf-8"))


def test_an_explicit_bundle_is_used_as_it_is_and_the_first_variable_set_wins(tmp_path):
    first, second = tmp_path / "ldo.pem", tmp_path / "requests.pem"
    first.write_text(TEST_CA)
    second.write_text(TEST_CA)
    environ = {"REQUESTS_CA_BUNDLE": str(second), "LDO_CA_BUNDLE": str(first)}
    assert trust.explicit_bundle(environ) == ("LDO_CA_BUNDLE", first)
    assert trust.explicit_bundle({"CURL_CA_BUNDLE": str(second)}) == ("CURL_CA_BUNDLE", second)
    assert trust.explicit_bundle({}) is None
    bundle = trust.resolve(environ=environ)
    assert (bundle.path, bundle.explicit) == (str(first), "LDO_CA_BUNDLE")


def test_an_explicit_bundle_that_is_not_there_says_how_to_opt_back_in(tmp_path):
    with pytest.raises(ConfigError) as caught:
        trust.explicit_bundle({"REQUESTS_CA_BUNDLE": str(tmp_path / "gone.pem")})
    assert "unset it to trust the OS store" in (caught.value.hint or "")


def test_the_windows_store_gives_server_authentication_certificates_only():
    der = ssl.PEM_cert_to_DER_cert(TEST_CA)
    entries = {
        "ROOT": [
            (der, "x509_asn", True),
            (der, "x509_asn", {"1.3.6.1.5.5.7.3.4"}),  # e-mail only: not for TLS
            (b"...", "pkcs_7_asn", True),
        ],
        "CA": [(der, "x509_asn", {trust._SERVER_AUTH})],
    }
    found = trust.system_certificates("win32", enum_certificates=entries.__getitem__)
    assert len(found) == 2
    assert all(item.startswith("-----BEGIN CERTIFICATE-----") for item in found)


def test_the_macos_store_is_read_with_security_from_the_system_keychains(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, TEST_CA + TEST_CA, "")

    monkeypatch.setattr(trust.Path, "exists", lambda self: True)
    found = trust.system_certificates("darwin", run=run)
    assert len(found) == 2
    assert calls[0][:4] == ["/usr/bin/security", "find-certificate", "-a", "-p"]
    assert "/Library/Keychains/System.keychain" in calls[0]


def test_the_linux_store_is_the_system_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "ca-certificates.crt"
    bundle.write_text(TEST_CA)
    paths = ssl.DefaultVerifyPaths(str(bundle), None, "SSL_CERT_FILE", str(bundle), "", "")
    monkeypatch.setattr(trust.ssl, "get_default_verify_paths", lambda: paths)
    assert trust.system_certificates("linux") == trust.split_pem(TEST_CA)


def test_a_store_that_cannot_be_read_leaves_the_public_roots(caplog):
    def broken(_store):
        raise OSError("access denied")

    assert trust.system_certificates("win32", enum_certificates=broken) == []
    assert "cannot read the system certificate store" in caplog.text


def test_the_combined_bundle_counts_what_each_source_added(tmp_path):
    extra = tmp_path / "corp.pem"
    extra.write_text(TEST_CA + BROKEN)
    body, counts = trust.build(extra, system=[PUBLIC[0], TEST_CA, BROKEN])
    # The OS store's copy of a public root is not counted twice, nor is the test CA once
    # the OS store has given it; the broken block is dropped, not fatal.
    assert (counts.public, counts.system, counts.extra) == (len(PUBLIC), 1, 0)
    assert body.count("BEGIN CERTIFICATE") == len(PUBLIC) + 1
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=body)


def test_ca_bundle_adds_its_certificates_and_must_hold_one(tmp_path):
    extra = tmp_path / "corp.pem"
    extra.write_text(TEST_CA)
    _, counts = trust.build(extra, system=[])
    assert (counts.system, counts.extra) == (0, 1)
    with pytest.raises(ConfigError, match="ca_bundle not found"):
        trust.build(tmp_path / "gone.pem", system=[])
    extra.write_text(BROKEN)
    with pytest.raises(ConfigError, match="no certificate OpenSSL can load"):
        trust.build(extra, system=[])


def test_the_bundle_file_is_named_by_its_content_and_reused(tmp_path):
    first = trust.write("one\n", tmp_path)
    assert first.name.startswith("ca-bundle-")
    assert trust.write("one\n", tmp_path) == first
    second = trust.write("two\n", tmp_path)
    assert second != first
    assert first.exists()  # an old bundle is kept for a week, not removed at once


def test_a_folder_that_cannot_be_written_gets_a_private_temporary_file(tmp_path):
    blocked = tmp_path / "file-not-folder"
    blocked.write_text("")
    path = trust.write("body\n", blocked / "cache")
    assert path.read_text() == "body\n"
    assert not path.is_relative_to(blocked)


def test_resolve_builds_once_per_process_in_the_users_cache(tmp_path):
    reads = []

    def system():
        reads.append(1)
        return [TEST_CA]

    environ = {"XDG_CACHE_HOME": str(tmp_path), "LOCALAPPDATA": str(tmp_path)}
    one = trust.resolve(environ=environ, system=system)
    two = trust.resolve(environ=environ, system=system)
    assert one == two
    assert len(reads) == 1
    assert Path(one.path).is_relative_to(tmp_path)
    assert (one.explicit, one.system) == (None, 1)


def test_the_cache_is_per_user_on_each_platform(tmp_path):
    assert trust.cache_dir({"LOCALAPPDATA": str(tmp_path)}, "win32") == tmp_path / "ldo" / "cache"
    assert trust.cache_dir({"XDG_CACHE_HOME": str(tmp_path)}, "linux") == tmp_path / "ldo"
