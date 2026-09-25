# Proxies and certificates

[Back to the docs](README.md)

Behind a corporate proxy, `ldo` works with the usual settings, and every HTTPS call it makes
goes the same way as the Azure CLI it runs, so both behave alike.

```bash
ldo network test                                  # the proxy, the certificates, each service
ldo network test --url https://intranet.corp.example/health
LDO_PROXY_ADDRESS=127.0.0.1:3129 ldo network test  # try a proxy before setting it anywhere
```

`network test` asks Entra ID, Graph, Azure Resource Manager and Defender (in the profile's
cloud), and each ServiceNow instance configured, for something they answer without a
sign-in, and expects a 2xx (Defender, which has nothing to show without a token, answers
401). It shows the proxy each call went through, which certificates are trusted, and when a
call fails, what to try. It exits 3 when any fails.

## The proxy

Each call takes the first of these that applies:

| | Setting | For |
| --- | --- | --- |
| 1 | this machine, and `169.254.169.254` | never a proxy: sign-in redirects to localhost, managed identity |
| 2 | `no_proxy` in the config file, and `NO_PROXY` | hosts that go direct, e.g. `.corp.example,10.0.0.0/8` |
| 3 | `LDO_PROXY_ADDRESS` | `ldo` alone, without changing `HTTPS_PROXY` for everything else |
| 4 | `proxy` in the config file | the same, kept in the file |
| 5 | `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY` | the usual variables, which most tools read |
| 6 | the operating system's proxy setting | Windows and macOS |

An address without a scheme, such as `127.0.0.1:3128`, means `http://`. Whichever proxy
applies, the Azure CLI gets it too, as `HTTPS_PROXY` and `NO_PROXY`.

```toml
proxy = "127.0.0.1:3128"
no_proxy = ".corp.example, 10.0.0.0/8"
```

### A proxy that wants NTLM or Kerberos

Corporate proxies often want a sign-in of their own, which a 407 from `network test` shows.
Neither `ldo` nor the Azure CLI speaks NTLM, so run a small local proxy that does, and point
`ldo` at it:

- [cntlm](https://cntlm.sourceforge.net/): set `Username`, `Domain` and `Proxy` in
  `cntlm.conf`, then `cntlm -H` for the password hashes and `cntlm -I -M
  https://graph.microsoft.com` to test them. It listens on `127.0.0.1:3128` unless its
  `Listen` line says otherwise.
- [Px](https://github.com/genotrance/px): the same on Windows, signing in as you with no
  password stored.

```bash
export LDO_PROXY_ADDRESS=127.0.0.1:3129    # wherever cntlm or Px listens
ldo network test
```

When nothing is set and a call cannot get out, `network test` looks for something listening
on 3128 or 3129 and suggests it. A 407 from a local proxy means it could not sign in
upstream: check its credentials.

Automatic proxy scripts (PAC and WPAD files) are not read: name the proxy instead.

## Certificates

A TLS-inspecting proxy re-signs every site with its own certificate. By default `ldo` trusts
three sets together, so it works where IT has installed that certificate on the machine:

- the public roots,
- the operating system's store: the Windows certificate store, the macOS system keychains,
  or the Linux system bundle,
- and any the config file's `ca_bundle` adds.

They are combined into one file in your cache folder (`~/.cache/ldo`, or
`%LOCALAPPDATA%\ldo\cache`), which the Azure CLI is handed as `REQUESTS_CA_BUNDLE`, so both
trust the same. The OS store only ever adds trust: public certificates still verify.

```toml
ca_bundle = "~/certs/corp-root.pem"   # the proxy's root, when it is not in the OS store
```

To use one bundle exactly as it is instead, nothing added, name it with `LDO_CA_BUNDLE`
(or the standard `REQUESTS_CA_BUNDLE` or `CURL_CA_BUNDLE`):

```bash
export LDO_CA_BUNDLE=/etc/corp/ca-bundle.pem
```

When a certificate does not verify, `network test` names who issued it: a proxy's own name
(Zscaler, Netskope, a company CA) shows it is inspecting traffic.

## In a container

The container's `127.0.0.1` is the container itself, so reach a cntlm on the host through
the host's name, and make cntlm listen where the container can reach it (`Listen 0.0.0.0:3129`,
with `Allow` set to the container network):

```bash
podman run --rm -it -e LDO_PROXY_ADDRESS=host.containers.internal:3129 \
  ghcr.io/libre-devops/python-helpers:latest network test
```

With docker, use `host.docker.internal` (on Linux, add `--add-host
host.docker.internal:host-gateway`). The image's own store is Debian's: mount a corporate
root and set `LDO_CA_BUNDLE`, or `ca_bundle` in a mounted config, when the proxy inspects TLS.
