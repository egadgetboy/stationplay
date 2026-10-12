"""The release workflow's own script (.github/workflows/release.yml), run
with stand-ins for gh and docker, in a git repository of its own.

Releases are source only (the owner, October 12): a version whose tests
passed is published with its zip, stationplay.yaml, docker-compose.yml and
the list of packages in the image its tests ran in, made by that very run.
No image is built, pushed or pulled, and nothing is published without that
list, without passed tests, or twice.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"

# Stand-ins: each logs what it was asked, and answers from files the test
# writes in $ASSETS: published (the tags out), runs (the image workflow's
# runs: commit, run, status), tested_<run> (its Test step's conclusion) and
# made_<run> (the package list that run kept).
GH = """#!/bin/bash
echo "gh $*" >> "$LOG"
case "$1 $2" in
  "release list") cat "$ASSETS/published" 2>/dev/null ;;
  "api repos/"*/workflows/*) cat "$ASSETS/runs" 2>/dev/null ;;
  "api repos/"*/jobs)
    run=$(sed 's|.*/runs/\\([0-9]*\\)/jobs|\\1|' <<< "$2")
    cat "$ASSETS/tested_$run" 2>/dev/null ;;
  "run download")
    # (gh run download <run> --name packages --dir <folder>)
    [ -f "$ASSETS/made_$3" ] || exit 1
    mkdir -p "$7" && cp "$ASSETS/made_$3" "$7/stationplay-1.32.1-packages.txt" ;;
  "release create") exit 0 ;;
  *) exit 0 ;;
esac
"""
DOCKER = """#!/bin/bash
echo "docker $*" >> "$LOG"
exit 0
"""


def script() -> str:
    """The "Publish what's new" step's script."""
    lines = WORKFLOW.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if "name: Publish what's new" in line)
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run + 1]) - len(lines[run + 1].lstrip())
    body = []
    for line in lines[run + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body) + "\n"


def git(work: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=work, capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip


@pytest.fixture
def run(tmp_path):
    """The script, in a repository where 1.32.0 is out and 1.32.1's commit
    has its notes on top: the log of what gh and docker were asked, and the
    exit status. `run.commit` is 1.32.1's commit."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, text in (("gh", GH), ("docker", DOCKER)):
        (bin_ / name).write_text(text)
        (bin_ / name).chmod((bin_ / name).stat().st_mode | stat.S_IEXEC)
    work = tmp_path / "work"
    (work / "app").mkdir(parents=True)
    (work / "docs" / "releases").mkdir(parents=True)
    git(work, "init", "-q", "-b", "main")
    (work / "app" / "__init__.py").write_text('__version__ = "1.32.1"\n')
    (work / "stationplay.yaml").write_text("services: {}\n")
    (work / "docker-compose.yml").write_text("services: {}\n")
    (work / "docs" / "releases" / "v1.32.0.md").write_text("---\ncommit: x\n---\n")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "StationPlay 1.32.1")
    commit = git(work, "rev-parse", "HEAD")
    (work / "docs" / "releases" / "v1.32.1.md").write_text(
        f"---\ncommit: {commit}\n---\n\nThe notes.\n"
    )
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "Release notes for 1.32.1")
    git(work, "update-ref", "refs/remotes/origin/main", "HEAD")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "published").write_text("v1.32.0\n")
    log = tmp_path / "log"
    (tmp_path / "temp").mkdir()

    def go() -> tuple[str, int, str]:
        env = {
            **os.environ,
            "PATH": f"{bin_}:{os.environ['PATH']}",
            "LOG": str(log),
            "ASSETS": str(assets),
            "RUNNER_TEMP": str(tmp_path / "temp"),
            "GITHUB_REPOSITORY": "egadgetboy/stationplay",
            "GITHUB_REPOSITORY_OWNER": "EgadgetBoy",
            "GH_TOKEN": "x",
            "FIRST_PUBLIC": "1.32.0",
        }
        done = subprocess.run(
            ["bash", "-e", "-c", script()], cwd=work, env=env, capture_output=True, text=True
        )
        return (log.read_text() if log.exists() else ""), done.returncode, done.stdout

    go.assets = assets  # type: ignore[attr-defined]
    go.commit = commit  # type: ignore[attr-defined]
    go.temp = tmp_path / "temp"  # type: ignore[attr-defined]
    return go


def image_run(run, status: str = "completed", test: str = "success", made: bool = True) -> None:
    """Image run 7, on 1.32.1's commit."""
    (run.assets / "runs").write_text(f"{run.commit} 7 {status}\n")
    (run.assets / "tested_7").write_text(test + "\n")
    if made:
        (run.assets / "made_7").write_text(
            "StationPlay 1.32.1: every package in the image its tests ran in\n"
        )


def docker(said: str) -> list[str]:
    return [line for line in said.splitlines() if line.startswith("docker ")]


def creates(said: str) -> list[str]:
    return [line for line in said.splitlines() if line.startswith("gh release create")]


def test_a_tested_version_is_published_with_its_tested_package_list(run):
    image_run(run)
    said, status, out = run()
    assert status == 0, said + out
    made = creates(said)
    assert len(made) == 1, said
    assert f"v1.32.1 --target {run.commit}" in made[0]
    for name in (
        "stationplay-1.32.1.zip",
        "stationplay.yaml",
        "docker-compose.yml",
        "stationplay-1.32.1-packages.txt",
    ):
        assert f"/{name}" in made[0], made[0]
    assert "gh run download 7 --name packages" in said  # (the very run that tested it)
    listed = run.temp / "v1.32.1" / "stationplay-1.32.1-packages.txt"
    assert listed.read_text() == (run.assets / "made_7").read_text()
    # (Source only: no image built, pushed or pulled, and no image's source.)
    assert not docker(said) and "ghcr" not in said and "gpl-source" not in said


def test_without_its_tested_package_list_nothing_is_published(run):
    image_run(run, made=False)
    said, status, out = run()
    assert status == 1
    assert not creates(said)
    assert "has no list of its packages" in out


def test_a_version_whose_tests_failed_isn_t_published(run):
    image_run(run, test="failure")
    said, status, out = run()
    assert status == 1
    assert not creates(said) and "run download" not in said
    assert "its tests didn't pass" in out


def test_a_version_still_being_tested_waits(run):
    image_run(run, status="in_progress")
    said, status, out = run()
    assert status == 0
    assert not creates(said)
    assert "waits for its tests" in out


def test_a_published_release_is_left_alone(run):
    image_run(run)
    (run.assets / "published").write_text("v1.32.0\nv1.32.1\n")
    said, status, out = run()
    assert status == 0, said + out
    assert not creates(said)
    assert "release upload" not in said and "run download" not in said and not docker(said)
