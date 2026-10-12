"""The source of FFmpeg, x264 and x265, at the exact versions in a
StationPlay image: Debian's source packages (each one's .dsc and the files
it names), downloaded into a folder.

StationPlay's own releases don't use it: they're source only, and publish
no image (the owner, October 12). It's here for anyone who builds an image
and hands it on to others, as a start: the GPL asks that the source go with
it, and that covers more packages than these three (see the image's
third-party-packages.txt).

It runs inside the image, as root, with a folder mounted at /out:

    docker run --rm -i --user 0 -v "$PWD/gpl:/out" stationplay:<version> python - < tools/gpl_source.py

Debian's archive (apt-get source) keeps only each suite's newest version,
so once Debian updates one of them, an older image's version comes from
snapshot.debian.org, which keeps every version, each file checked against
the hashes snapshot gives and the .dsc lists. A version neither has stops
it, saying which.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import quote

SOURCES = ("ffmpeg", "x264", "x265")
SNAPSHOT = "https://snapshot.debian.org"
OUT = Path("/out")


def installed_versions(listing: str) -> dict[str, str]:
    """Each source package's version, from dpkg-query's
    `${source:Package} ${source:Version}` lines (the first for each)."""
    found: dict[str, str] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2:
            found.setdefault(parts[0], parts[1])
    return found


def snapshot_files(answer: dict) -> list[tuple[str, str]]:
    """The files of a source package at one version, from snapshot's
    srcfiles?fileinfo=1 answer: (name, sha1) for each, the .dsc first."""
    files = []
    for entry in answer.get("result", []):
        sha1 = entry.get("hash", "")
        infos = answer.get("fileinfo", {}).get(sha1, [])
        if infos and re.fullmatch(r"[0-9a-f]{40}", sha1):
            files.append((Path(infos[0]["name"]).name, sha1))
    return sorted(files, key=lambda f: (not f[0].endswith(".dsc"), f[0]))


def dsc_sha256(dsc: str) -> dict[str, str]:
    """The files a .dsc names, with their SHA-256s (Checksums-Sha256)."""
    sums: dict[str, str] = {}
    inside = False
    for line in dsc.splitlines():
        if line.startswith("Checksums-Sha256:"):
            inside = True
        elif inside and line.startswith(" "):
            parts = line.split()
            if len(parts) == 3:
                sums[parts[2]] = parts[0]
        elif inside:
            inside = False
    return sums


def check(folder: Path, dsc_name: str) -> None:
    """Every file the .dsc names is in `folder`, as the .dsc says. Raises
    ValueError if one isn't."""
    for name, wanted in dsc_sha256((folder / dsc_name).read_text(errors="replace")).items():
        got = folder / name
        if not got.is_file() or hashlib.sha256(got.read_bytes()).hexdigest() != wanted:
            raise ValueError(f"{name} isn't as {dsc_name} says")


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as answer:  # (fixed https addresses)
        return answer.read()


def from_snapshot(source: str, version: str, out: Path) -> None:
    """A source package at one version, from snapshot.debian.org."""
    answer = json.loads(
        _get(f"{SNAPSHOT}/mr/package/{quote(source)}/{quote(version, safe='')}/srcfiles?fileinfo=1")
    )
    files = snapshot_files(answer)
    if not files or not files[0][0].endswith(".dsc"):
        raise ValueError(f"snapshot.debian.org has no {source} {version}")
    for name, sha1 in files:
        data = _get(f"{SNAPSHOT}/file/{sha1}")
        if hashlib.sha1(data).hexdigest() != sha1:  # (snapshot names files by SHA-1)
            raise ValueError(f"{name} from snapshot.debian.org isn't as it should be")
        (out / name).write_bytes(data)
    check(out, files[0][0])


def main() -> int:
    listing = subprocess.run(
        ["dpkg-query", "-W", "-f", "${source:Package} ${source:Version}\n"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    versions = installed_versions(listing)
    sources = Path("/etc/apt/sources.list.d/debian.sources")
    sources.write_text(re.sub(r"(?m)^Types: deb$", "Types: deb deb-src", sources.read_text()))
    apt = subprocess.run(["apt-get", "update", "-qq"], capture_output=True, text=True)
    for source in SOURCES:
        version = versions.get(source)
        if not version:
            print(f"The image has nothing built from {source}", file=sys.stderr)
            return 1
        got = apt.returncode == 0 and subprocess.run(
            ["apt-get", "source", "--download-only", "-qq", f"{source}={version}"],
            cwd=OUT, capture_output=True, text=True,
        ).returncode == 0  # fmt: skip
        try:
            if got:
                check(OUT, next(p.name for p in OUT.glob(f"{source}_*.dsc")))
                print(f"{source} {version} (from Debian's archive)")
            else:
                from_snapshot(source, version, OUT)
                print(f"{source} {version} (from snapshot.debian.org)")
        except (OSError, ValueError, StopIteration) as e:
            print(f"Couldn't get {source} {version}'s source: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
