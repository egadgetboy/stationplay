"""The release workflow's own script (.github/workflows/release.yml), run
with stand-ins for gh and docker: a release published before releases
carried what their image is made of gets those files, once, and a problem
with one release never stops the rest (the audit of 1.32.1)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"

# Stand-ins: each logs what it was asked, and answers from files the test
# writes (assets/<tag>: a release's files, one name a line).
GH = """#!/bin/bash
echo "gh $*" >> "$LOG"
case "$1 $2" in
  "release list") printf 'v1.32.0\\nv1.32.1\\n' ;;
  "api repos/"*) exit 0 ;;
  "release view")
    [ -f "$ASSETS/$3.fail" ] && exit 1
    # (A name at a time, as gh writes them: a reader that stops early can
    # make this fail.)
    while read -r name; do echo "$name" || exit 141; done < "$ASSETS/$3" ;;
  "release upload")
    [ -f "$ASSETS/upload.fail" ] && exit 1
    exit 0 ;;
  *) exit 0 ;;
esac
"""
DOCKER = """#!/bin/bash
echo "docker $*" >> "$LOG"
case "$1" in
  pull) exit 0 ;;
  run)
    # (python - <version>: the package list; -v <folder>:/out: the source.)
    for arg in "$@"; do
      case "$arg" in *:/out) touch "${arg%:/out}/ffmpeg_7.1.dsc" ;; esac
    done
    cat > /dev/null
    echo "a package list" ;;
  *) exit 0 ;;
esac
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


@pytest.fixture
def run(tmp_path):
    """The script, in a folder with releases 1.32.0 and 1.32.1 published:
    the log of what gh and docker were asked, and the exit status."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, text in (("gh", GH), ("docker", DOCKER)):
        (bin_ / name).write_text(text)
        (bin_ / name).chmod((bin_ / name).stat().st_mode | stat.S_IEXEC)
    work = tmp_path / "work"
    (work / "docs" / "releases").mkdir(parents=True)
    (work / "tools").mkdir()
    for version in ("1.32.0", "1.32.1"):
        (work / "docs" / "releases" / f"v{version}.md").write_text("---\ncommit: x\n---\n")
    for tool in ("sbom.py", "gpl_source.py"):
        (work / "tools" / tool).write_text("# a tool\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    log = tmp_path / "log"
    (tmp_path / "temp").mkdir()

    def go() -> tuple[str, int]:
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
        return (log.read_text() if log.exists() else ""), done.returncode

    go.assets = assets  # type: ignore[attr-defined]
    return go


def full(version: str) -> str:
    return "\n".join([
        "docker-compose.yml", f"stationplay-{version}-gpl-source.tar",
        f"stationplay-{version}-packages.txt", f"stationplay-{version}.zip", "stationplay.yaml",
    ])  # fmt: skip


def test_a_release_without_its_source_gets_it_and_the_next_is_still_looked_at(run):
    (run.assets / "v1.32.0").write_text("docker-compose.yml\nstationplay-1.32.0-packages.txt\n")
    (run.assets / "v1.32.1").write_text(full("1.32.1") + "\n")
    said, status = run()
    assert status == 0, said
    uploads = [line for line in said.splitlines() if line.startswith("gh release upload")]
    assert len(uploads) == 1 and "--clobber v1.32.0" in uploads[0]  # (replacing a half-upload)
    assert "ghcr.io/egadgetboy/stationplay:1.32.0" in said  # (its own image, lower case)
    assert "gh release view v1.32.1" in said


def test_a_failed_upload_doesn_t_stop_the_next_release(run):
    (run.assets / "v1.32.0").write_text("docker-compose.yml\n")
    (run.assets / "v1.32.1").write_text(full("1.32.1") + "\n")
    (run.assets / "upload.fail").write_text("")
    said, status = run()
    assert status == 1  # (refused, said on the run's page)
    assert "gh release view v1.32.1" in said


def test_a_release_with_its_source_is_left_alone(run):
    """However its files are listed: its tar first, before others still to
    come (a grep that stops early mustn't make it look missing)."""
    for version in ("1.32.0", "1.32.1"):
        (run.assets / f"v{version}").write_text(
            f"stationplay-{version}-gpl-source.tar\n" + "\n".join(f"other-{n}" for n in range(500))
        )
    said, status = run()
    assert status == 0, said
    assert "gh release upload" not in said and "docker" not in said


def test_files_that_can_t_be_listed_aren_t_taken_as_missing(run):
    (run.assets / "v1.32.0.fail").write_text("")
    (run.assets / "v1.32.1").write_text(full("1.32.1") + "\n")
    said, status = run()
    assert status == 1
    assert "gh release upload" not in said and "docker" not in said
    assert "gh release view v1.32.1" in said
