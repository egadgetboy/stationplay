"""What was in the image built and tested for a release, package by
package, with where each one's source is kept: the list each release
carries (tapioca-<version>-packages.txt). It's the image people build
(the tests' own stage adds pytest, git and jq, which aren't listed).

Every Debian package installed, at its exact version, with the source
package it's built from and that source's page on snapshot.debian.org
(which keeps every version Debian has published); and every Python package,
with its license and its page on PyPI. tapiOca's own source is the
release's zip. From 1.34.0 the image that was tested is the one published
(the owner, October 12: D4 is No), and the source of its GPL and LGPL
packages goes with the release (tapioca-<version>-source.tar).

It runs inside the image (the image workflow runs it, piped in, after the
tests, so the image needs nothing more):

    docker run --rm -i stationplay:latest python - <version> < tools/sbom.py
"""

from __future__ import annotations

import platform
import subprocess
import sys
from importlib import metadata
from urllib.parse import quote

DPKG_FORMAT = "${db:Status-Abbrev}\t${Package}\t${Version}\t${source:Package}\t${source:Version}\n"


def debian_rows(listing: str) -> list[tuple[str, str, str, str]]:
    """The installed packages in dpkg-query's listing (DPKG_FORMAT): each
    one's name, version, source package and source version, by name."""
    rows = []
    for line in listing.splitlines():
        parts = line.split("\t")
        if len(parts) != 5 or not parts[0].startswith("ii"):
            continue
        _, name, version, source, source_version = parts
        rows.append((name, version, source or name, source_version or version))
    return sorted(rows)


def license_of(meta) -> str:
    """A Python package's license, in a few words."""
    said = (meta.get("License-Expression") or "").strip()
    if not said:
        # (Its first line: a License field may hold the license's whole text.)
        said = next(iter((meta.get("License") or "").strip().splitlines()), "").strip()
    if not said or len(said) > 60:
        classifiers = [
            c.rsplit(" :: ", 1)[-1]
            for c in meta.get_all("Classifier") or []
            if c.startswith("License ::")
        ]
        said = ", ".join(classifiers) if classifiers else said
    return said[:60] if said else "see its page"


def python_rows(distributions) -> list[tuple[str, str, str]]:
    """Each installed Python package: its name, version and license, by
    name (each once)."""
    seen: dict[str, tuple[str, str, str]] = {}
    for dist in distributions:
        name = dist.metadata.get("Name") or ""
        if name and name.lower() not in seen:
            seen[name.lower()] = (name, dist.version, license_of(dist.metadata))
    return sorted(seen.values(), key=lambda row: row[0].lower())


def snapshot(source: str, version: str) -> str:
    """Where Debian keeps a source package at that exact version."""
    return (
        f"https://snapshot.debian.org/package/{quote(source, safe='')}/{quote(version, safe='')}/"
    )


def report(
    version: str,
    debian: list[tuple[str, str, str, str]],
    python: list[tuple[str, str, str]],
    python_version: str = "",
    arch: str = "",
) -> str:
    lines = [
        f"tapiOca {version}: every package in the image that was tested",
        "",
        "Each Debian package at its exact version, with the source package it's",
        "built from and where Debian keeps that source. Each package's own",
        "license is in the image, in /usr/share/doc/<package>/copyright.",
        f"tapiOca's own source is tapioca-{version}.zip, under the AGPL.",
        f"This image is published as ghcr.io/egadgetboy/tapioca-server:{version}"
        + (f" (this list is its {arch} image's)." if arch else "."),
        "The source of its GPL and LGPL packages, as Debian publishes it, is",
        f"tapioca-{version}-source.tar, beside this list. An image built from",
        "the zip instead gets Debian's packages from Debian, as they are on the",
        "day it's built, and lists them in /opt/stationplay/third-party-packages.txt.",
        "",
        f"Debian packages ({len(debian)})",
        "",
    ]
    lines += [f"{n} {v}: source {s} {sv}, {snapshot(s, sv)}" for n, v, s, sv in debian]
    if python_version:
        lines += [
            "",
            "Python itself",
            "",
            f"Python {python_version} (the python image's own, under the PSF license), "
            f"https://www.python.org/ftp/python/{python_version}/Python-{python_version}.tgz",
        ]
    lines += ["", f"Python packages ({len(python)})", ""]
    lines += [f"{n} {v}: {lic}, https://pypi.org/project/{n}/{v}/" for n, v, lic in python]
    return "\n".join(lines) + "\n"


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "?"
    listing = subprocess.run(
        ["dpkg-query", "-W", "-f", DPKG_FORMAT], capture_output=True, text=True, check=True
    ).stdout
    rows = python_rows(metadata.distributions())
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
    sys.stdout.write(report(version, debian_rows(listing), rows, platform.python_version(), arch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
