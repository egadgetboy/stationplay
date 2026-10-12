"""A quick check, before pushing to main: the tests that read tapiOca's
own files (the Dockerfile, the docs, a tool) find them in the image too.

The image's tests run in the Dockerfile's test stage, which has only what
the Dockerfile copies in and .dockerignore lets through. A test that reads
a file the image hasn't got fails there, 40 minutes into the image workflow
(as 1.32.0's first image run did). This lays the project out as the image
has it, in a folder of its own, collects every test there (an import of a
missing file shows), and runs each test file that reaches outside the
tests folder. It takes about 3 minutes.

    python tools/image_check.py          # the check
    python tools/image_check.py --list   # only which test files it runs

The image workflow runs the same test files in the image itself, first, so
the long tests are skipped when one of these fails.
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# A test reaches outside the tests folder this way (Path(__file__).parents[1],
# ROOT = ....parent.parent, WEB_DIR.parent.parent, dirname(dirname(__file__)),
# HERE / ".."). (Not "../" in a string: the tests try those as attacks.)
REACHES_OUT = re.compile(
    r"parent\.parent|parents\[|dirname\(\s*(os\.path\.)?dirname\(|/\s*\"\.\.\""
)
SKIPPED = ("__pycache__", ".pytest_cache")


def stages(dockerfile: str) -> dict[str, list[tuple[list[str], str]]]:
    """Each stage's COPY instructions (sources, destination), by the stage's
    name (its AS, or its number); copies from another stage are left out."""
    text = re.sub(r"\\\n", " ", dockerfile)
    found: dict[str, list[tuple[list[str], str]]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        word, _, rest = line.partition(" ")
        if word.upper() == "FROM":
            parts = rest.split()
            current = parts[2] if len(parts) >= 3 and parts[1].upper() == "AS" else str(len(found))
            found[current] = []
        elif word.upper() == "COPY" and current is not None:
            parts = rest.split()
            if any(p.startswith("--from") for p in parts):
                continue
            parts = [p for p in parts if not p.startswith("--")]
            found[current].append((parts[:-1], parts[-1]))
    return found


def _base(dockerfile: str, stage: str) -> str | None:
    """The stage a stage is built on, if it's one of this Dockerfile's."""
    for raw in re.sub(r"\\\n", " ", dockerfile).splitlines():
        parts = raw.split()
        if (
            len(parts) >= 4
            and parts[0].upper() == "FROM"
            and parts[2].upper() == "AS"
            and parts[3] == stage
        ):
            return parts[1]
    return None


def copies_for(dockerfile: str, stage: str) -> list[tuple[list[str], str]]:
    """Every COPY that goes into `stage`, its base stages' first."""
    every = stages(dockerfile)
    chain = []
    at: str | None = stage
    while at is not None and at in every and at not in chain:
        chain.append(at)
        at = _base(dockerfile, at)
    return [c for name in reversed(chain) for c in every[name]]


def _parse_ignore(text: str) -> list[tuple[bool, list[str]]]:
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keep = line.startswith("!")
        pattern = line[1:] if keep else line
        parts = [p for p in pattern.strip("/").split("/") if p and p != "."]
        if parts:
            rules.append((keep, parts))
    return rules


def _matches(pattern: list[str], path: list[str]) -> bool:
    """A .dockerignore pattern against a path from the project's top, as
    Docker matches them: `*` within one folder's name, `**` across any."""
    if not pattern:
        return not path
    if pattern[0] == "**":
        return any(_matches(pattern[1:], path[i:]) for i in range(len(path) + 1))
    return (
        bool(path) and fnmatch.fnmatchcase(path[0], pattern[0]) and _matches(pattern[1:], path[1:])
    )


def ignored(rules: list[tuple[bool, list[str]]], relative: str) -> bool:
    """Whether .dockerignore's rules leave a file out of what Docker sees:
    a pattern that matches the file or a folder it's in leaves it out, a !
    one brings it back, and the last that matches decides."""
    parts = relative.split("/")
    out = False
    for keep, pattern in rules:
        if any(_matches(pattern, parts[:k]) for k in range(1, len(parts) + 1)):
            out = not keep
    return out


def tracked(root: Path) -> set[str] | None:
    """The files git has (committed or added), as the image workflow's
    checkout has them; None if root isn't a git checkout."""
    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return {name for name in listed.decode().split("\0") if name}


def lay_out(root: Path, into: Path, stage: str = "test", only: set[str] | None = None) -> list[str]:
    """Copies what `stage` of root's Dockerfile has into `into`, as the
    image has it in its working folder; the files, relative to `into`.
    `only`: the files there are (git's), so one never added isn't laid out,
    as the image workflow's checkout wouldn't have it."""
    dockerfile = (root / "Dockerfile").read_text()
    ignore = root / ".dockerignore"
    rules = _parse_ignore(ignore.read_text()) if ignore.is_file() else []
    laid: list[str] = []
    for sources, dest in copies_for(dockerfile, stage):
        into_folder = dest.endswith("/") or dest in (".", "./") or len(sources) > 1
        for source in sources:
            start = root / source
            files = (
                [start] if start.is_file() else sorted(p for p in start.rglob("*") if p.is_file())
            )
            for f in files:
                relative = f.relative_to(root).as_posix()
                if (
                    ignored(rules, relative)
                    or any(s in f.parts for s in SKIPPED)
                    or f.suffix == ".pyc"
                    or (only is not None and relative not in only)
                ):
                    continue
                if start.is_file():
                    target = into / dest / f.name if into_folder else into / dest
                else:
                    target = into / dest / f.relative_to(start)
                target = target.resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
                laid.append(target.relative_to(into.resolve()).as_posix())
    return laid


def reaching_out(tests: Path) -> list[str]:
    """The test files that read something outside the tests folder."""
    return sorted(
        f"tests/{f.name}"
        for f in tests.glob("test_*.py")
        if REACHES_OUT.search(f.read_text(encoding="utf-8"))
    )


def main() -> int:
    chosen = reaching_out(ROOT / "tests")
    if "--list" in sys.argv[1:]:
        print(" ".join(chosen))
        return 0
    with tempfile.TemporaryDirectory(prefix="stationplay-image-") as folder:
        laid_out = Path(folder)
        lay_out(ROOT, laid_out, only=tracked(ROOT))
        pytest = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        print("Collecting every test, laid out as in the image…", flush=True)
        collected = subprocess.run(
            [*pytest, "--collect-only"], cwd=laid_out, capture_output=True, text=True
        )
        if collected.returncode != 0:
            print(collected.stdout[-4000:], collected.stderr[-2000:], sep="\n")
            print("The image's tests can't all be collected: see above.")
            return 1
        print(
            f"Running the {len(chosen)} test files that read the project's own files…", flush=True
        )
        ran = subprocess.run([*pytest, *chosen], cwd=laid_out)
        if ran.returncode != 0:
            print(
                "A test that reads the project's own files fails as the image has them: see above."
            )
            return ran.returncode
    print("The image's tests have the files they read.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
