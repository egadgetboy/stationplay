"""What's in StationPlay's image, package by package, with where each one's
source is kept: the list each release carries
(stationplay-<version>-packages.txt).

Every Debian package installed, at its exact version, with the source
package it's built from and that source's page on snapshot.debian.org
(which keeps every version Debian has published); and every Python package,
with its license and its page on PyPI. StationPlay's own source is the
release's zip.

It runs inside the image (release.yml runs it, piped in, so the image needs
nothing more):

    docker run --rm -i ghcr.io/<you>/stationplay:<version> python - <version> < tools/sbom.py
"""

from __future__ import annotations

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
        said = (meta.get("License") or "").strip().splitlines()[0] if meta.get("License") else ""
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
    version: str, debian: list[tuple[str, str, str, str]], python: list[tuple[str, str, str]]
) -> str:
    lines = [
        f"StationPlay {version}: every package in its image",
        "",
        "Each Debian package at its exact version, with the source package it's",
        "built from and where Debian keeps that source. Each package's own",
        "license is in the image, in /usr/share/doc/<package>/copyright. FFmpeg's,",
        "x264's and x265's source is also in this release's",
        f"stationplay-{version}-gpl-source.tar. StationPlay's own source is",
        f"stationplay-{version}.zip, under the AGPL.",
        "",
        f"Debian packages ({len(debian)})",
        "",
    ]
    lines += [f"{n} {v}: source {s} {sv}, {snapshot(s, sv)}" for n, v, s, sv in debian]
    lines += ["", f"Python packages ({len(python)})", ""]
    lines += [f"{n} {v}: {lic}, https://pypi.org/project/{n}/{v}/" for n, v, lic in python]
    return "\n".join(lines) + "\n"


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "?"
    listing = subprocess.run(
        ["dpkg-query", "-W", "-f", DPKG_FORMAT], capture_output=True, text=True, check=True
    ).stdout
    sys.stdout.write(report(version, debian_rows(listing), python_rows(metadata.distributions())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
