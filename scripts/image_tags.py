"""The tags a published container image gets, one per line.

    python scripts/image_tags.py --version 0.2.1 --variant tool --stamp 20260924.57 --latest

A release gets its exact version, the floating minor (and, from 1.0, major) tag, and
``latest`` when it is the newest release: that is the image with the Azure CLI, which
works with the default sign-in. The tool alone gets the same with a ``-slim`` suffix, and
``slim`` for its newest. Every build also gets an immutable tag with a stamp (the build
date and run), so a weekly patched rebuild can be pinned. A pre-release gets only its
exact version and stamp: nothing floats to it.
"""

from __future__ import annotations

import argparse
import re
import sys

# The image variants: the Containerfile target, and the suffix its tags carry.
VARIANTS = {"az": "", "tool": "-slim"}
_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TAG_SAFE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")
_STAMP = re.compile(r"^\d{8}(\.\d+)?$")
MAX_TAG = 128  # the OCI distribution limit


def image_tags(
    version: str, variant: str = "az", *, stamp: str | None = None, latest: bool = False
) -> list[str]:
    """Every tag for ``version`` of ``variant``, most specific first."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}: use one of {', '.join(VARIANTS)}")
    if not _TAG_SAFE.match(version):
        raise ValueError(f"version {version!r} cannot be used in an image tag")
    if stamp is not None and not _STAMP.match(stamp):
        raise ValueError(f"stamp {stamp!r} must be a date, YYYYMMDD, optionally .RUN")
    suffix = VARIANTS[variant]
    tags = [f"{version}{suffix}"]
    release = _RELEASE.match(version)
    if release:
        major, minor, _ = release.groups()
        tags.append(f"{major}.{minor}{suffix}")
        # Before 1.0 a minor release may break things, so nothing floats across them.
        if major != "0":
            tags.append(f"{major}{suffix}")
        if latest:
            tags.append(suffix.lstrip("-") or "latest")
    if stamp:
        tags.append(f"{version}{suffix}-{stamp}")
    too_long = [tag for tag in tags if len(tag) > MAX_TAG]
    if too_long:
        raise ValueError(f"tags longer than {MAX_TAG} characters: {', '.join(too_long)}")
    return tags


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", required=True, help="the version the image holds")
    parser.add_argument("--variant", default="az", choices=sorted(VARIANTS))
    parser.add_argument("--stamp", help="build stamp for the immutable tag, YYYYMMDD[.RUN]")
    parser.add_argument("--latest", action="store_true", help="this is the newest release")
    parser.add_argument("--image", help="prefix each tag with this image, as IMAGE:TAG")
    args = parser.parse_args(argv)
    try:
        tags = image_tags(args.version, args.variant, stamp=args.stamp, latest=args.latest)
    except ValueError as exc:
        parser.error(str(exc))
    for tag in tags:
        print(f"{args.image}:{tag}" if args.image else tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
