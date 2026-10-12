"""The source of the GPL and LGPL packages in a tapiOca image, at the
exact versions in it: Debian's source packages (each one's .dsc and the
files it names), downloaded into a folder.

With --all, every source package that an installed package whose copyright
file names the GPL, the LGPL or the AGPL (any version) is built from; a
package without a copyright file counts too, as it can't be told. With
--also <list> too (another image's tapioca-<version>-packages.txt, such
as the arm64 image's), the source of each package in that list that isn't
installed here at that very version, whatever its license (a source in both
images at different versions is fetched at each). Without --all, only
FFmpeg, x264 and x265's.

release.yml runs it for each release from 1.34.0, in the image that was
tested (the owner, October 12: the image is published, with this source
attached, C6). It runs inside the image, as root, with a folder mounted at
/out:

    docker run --rm -i --user 0 -v "$PWD/gpl:/out" stationplay:<version> python - --all < tools/gpl_source.py

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
DOCS = Path("/usr/share/doc")
# A copyright file naming the GPL, the LGPL or the AGPL, in any version.
GPL = re.compile(
    r"\b(?:L|A)?GPL\b|GNU (?:Lesser |Library |Affero )?General Public Licen[cs]e", re.I
)
# A line of a package list (tools/sbom.py): a Debian package, its version,
# and its source package and version.
LISTED = re.compile(r"^(\S+) (\S+): source (\S+) (\S+), https://snapshot\.debian\.org/")


def installed_versions(listing: str) -> dict[str, str]:
    """Each source package's version, from dpkg-query's
    `${source:Package} ${source:Version}` lines (the first for each)."""
    found: dict[str, str] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2:
            found.setdefault(parts[0], parts[1])
    return found


def gpl_sources(listing: str, copyright_of) -> dict[str, str]:
    """Each source package (and its version) an installed package is built
    from whose copyright file names the GPL, LGPL or AGPL, or that has none
    (`listing`: dpkg-query's `${Package} ${source:Package} ${source:Version}`
    lines; `copyright_of(package)`: its copyright file's text, or None)."""
    found: dict[str, str] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        package, source, version = parts
        text = copyright_of(package)
        if text is None or GPL.search(text):
            found.setdefault(source, version)
    return found


def listed_sources(listed: str, installed: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Each source package and its version, of a package in a package list
    (tools/sbom.py's) that isn't one of `installed` (each package and its
    version: one installed at another version is another package)."""
    return {
        (got[3], got[4])
        for line in listed.splitlines()
        if (got := LISTED.match(line)) and (got[1], got[2]) not in installed
    }


def _copyright(package: str) -> str | None:
    path = DOCS / package.split(":")[0] / "copyright"
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


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


def wanted(args: list[str]) -> list[tuple[str, str]] | str:
    """The source packages to fetch, each with its version, in order (see
    the module's notes), or why it can't be said."""

    def dpkg(fmt: str) -> str:
        return subprocess.run(
            ["dpkg-query", "-W", "-f", fmt], capture_output=True, text=True, check=True
        ).stdout

    if "--all" not in args:
        versions = installed_versions(dpkg("${source:Package} ${source:Version}\n"))
        missing = [s for s in SOURCES if s not in versions]
        if missing:
            return f"The image has nothing built from {missing[0]}"
        return [(s, versions[s]) for s in SOURCES]
    listing = dpkg("${Package} ${source:Package} ${source:Version}\n")
    found = set(gpl_sources(listing, _copyright).items())
    if "--also" in args:
        at = args.index("--also") + 1
        if at >= len(args):
            return "--also needs a package list"
        installed = {
            (parts[0], parts[1])
            for line in dpkg("${Package} ${Version}\n").splitlines()
            if len(parts := line.split()) == 2
        }
        found |= listed_sources(Path(args[at]).read_text(), installed)
    return sorted(found)


def main(args: list[str] | None = None) -> int:
    chosen = wanted(sys.argv[1:] if args is None else args)
    if isinstance(chosen, str):
        print(chosen, file=sys.stderr)
        return 1
    sources = Path("/etc/apt/sources.list.d/debian.sources")
    sources.write_text(re.sub(r"(?m)^Types: deb$", "Types: deb deb-src", sources.read_text()))
    apt = subprocess.run(["apt-get", "update", "-qq"], capture_output=True, text=True)
    for source, version in chosen:
        got = apt.returncode == 0 and subprocess.run(
            ["apt-get", "source", "--download-only", "-qq", f"{source}={version}"],
            cwd=OUT, capture_output=True, text=True,
        ).returncode == 0  # fmt: skip
        try:
            if got:
                check(OUT, _dsc_name(source, version))
                print(f"{source} {version} (from Debian's archive)")
            else:
                from_snapshot(source, version, OUT)
                print(f"{source} {version} (from snapshot.debian.org)")
        except (OSError, ValueError, StopIteration) as e:
            print(f"Couldn't get {source} {version}'s source: {e}", file=sys.stderr)
            return 1
    return 0


def _dsc_name(source: str, version: str) -> str:
    """A source package's .dsc, as Debian names it (the version without
    its epoch)."""
    return f"{source}_{version.split(':', 1)[-1]}.dsc"


if __name__ == "__main__":
    raise SystemExit(main())
