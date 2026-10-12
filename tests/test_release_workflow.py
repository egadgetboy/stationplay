"""The release workflow's own script (.github/workflows/release.yml), run
with stand-ins for gh, docker, skopeo and ssh-keygen, in a git repository
of its own.

Releases are source only (the owner, October 12): a version whose tests
passed is published with its zip, stationplay.yaml, docker-compose.yml and
the list of packages in the image that was tested, made by a run that
passed (the image workflow's "Made of" step, read here for the artifact's
name and file). No image is built, pushed or pulled, and nothing is
published without that list, without passed tests, or twice. One version
that can't be published never stops the next (the audit of 1.32.1).

From 1.34.0 (the owner, October 12, later the same day: D4 is No, U1), the
image is published too: the very one the image workflow tested, by digest,
gets the version's tags (C7), and the release carries the arm64 image's
package list, the source of the images' GPL and LGPL packages (C6), and the
zip's signature, which is required from 1.35.0. Versions before 1.34.0
publish as they did.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
IMAGE = ROOT / ".github" / "workflows" / "image.yml"

# Stand-ins: each logs what it was asked, and answers from files the test
# writes in $ASSETS: published (the tags out), runs (the image workflow's
# runs: commit, run, status), tested_<run> (its Test step's conclusion) and
# made_<run>/ (the files that run kept, under the artifact's name, $ARTIFACT,
# which the test reads from image.yml).
GH = """#!/bin/bash
echo "gh $*" >> "$LOG"
case "$1 $2" in
  "release list") cat "$ASSETS/published" 2>/dev/null ;;
  "api repos/"*/workflows/*) cat "$ASSETS/runs" 2>/dev/null ;;
  "api repos/"*/jobs)
    run=$(sed 's|.*/runs/\\([0-9]*\\)/jobs|\\1|' <<< "$2")
    cat "$ASSETS/tested_$run" 2>/dev/null ;;
  "run download")
    # (gh run download <run> --name <artifact> --dir <folder>)
    [ "$4 $5 $6" = "--name $ARTIFACT --dir" ] || exit 2
    [ -d "$ASSETS/made_$3" ] || exit 1
    mkdir -p "$7" && cp "$ASSETS/made_$3"/* "$7/" ;;
  "release create") exit 0 ;;
  *) exit 0 ;;
esac
"""
DOCKER = """#!/bin/bash
echo "docker $*" >> "$LOG"
# (Fetching the source: a file in the folder mounted at /out, unless the
# test says it can't be had.)
if [ "$1" = run ]; then
  for a in "$@"; do
    case "$a" in
      *:/out) [ -e "$ASSETS/no_source" ] && exit 1
              mkdir -p "${a%:/out}" && echo source > "${a%:/out}/ffmpeg_7.1.5-0+deb13u1.dsc" ;;
    esac
  done
fi
[ "$1" = run ] || [ "$1" = login ] && cat > /dev/null
exit 0
"""
# (The registry: what a tag holds now is $ASSETS/manifest.)
SKOPEO = """#!/bin/bash
echo "skopeo $*" >> "$LOG"
case "$1" in
  login) cat > /dev/null ;;
  inspect) cat "$ASSETS/manifest" ;;
esac
exit 0
"""
# (Signing: the .sig beside the file, unless the test says the key won't do.)
SSH_KEYGEN = """#!/bin/bash
echo "ssh-keygen $*" >> "$LOG"
[ -e "$ASSETS/key_wont_do" ] && exit 1
if [ "$2" = sign ]; then echo signature > "${@: -1}.sig"; fi
exit 0
"""
MANIFEST = "the two tested images, joined\n"


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


def made_of() -> tuple[str, str]:
    """What image.yml keeps for release.yml: the artifact's name, and the
    package list's file name, with <version> for the version."""
    text = IMAGE.read_text()
    upload = re.search(
        r"uses: actions/upload-artifact@\S+\n\s+with:\n\s+name: (\S+)\n\s+path: (.+)\n", text
    )
    assert upload, "image.yml keeps the package list as an artifact"
    name, path = upload.groups()
    assert path == "${{ runner.temp }}/made/"
    made = re.search(r'> "\$RUNNER_TEMP/made/(stationplay-\$version-packages\.txt)"', text)
    assert made, "image.yml writes the package list into that folder"
    return name, made.group(1).replace("$version", "<version>")


def git(work: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=work, capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip


@pytest.fixture
def run(tmp_path):
    """The script, in a repository where 1.32.0 is out and 1.32.1's commit
    has its notes on top: the log of what gh and docker were asked, the
    exit status and what it said. `run.commits` has each version's commit;
    `run.version("1.32.2")` adds another version, with its notes."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, text in (("gh", GH), ("docker", DOCKER), ("skopeo", SKOPEO),
                       ("ssh-keygen", SSH_KEYGEN)):  # fmt: skip
        (bin_ / name).write_text(text)
        (bin_ / name).chmod((bin_ / name).stat().st_mode | stat.S_IEXEC)
    work = tmp_path / "work"
    (work / "app").mkdir(parents=True)
    (work / "docs" / "releases").mkdir(parents=True)
    git(work, "init", "-q", "-b", "main")
    (work / "stationplay.yaml").write_text("services: {}\n")
    (work / "docker-compose.yml").write_text("services: {}\n")
    (work / "tools").mkdir()
    (work / "tools" / "gpl_source.py").write_text("# (a stand-in: the image runs it)\n")
    (work / "docs" / "releases" / "v1.32.0.md").write_text("---\ncommit: x\n---\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "published").write_text("v1.32.0\n")
    log = tmp_path / "log"
    (tmp_path / "temp").mkdir()
    artifact, listed = made_of()
    commits: dict[str, str] = {}

    def version(number: str) -> str:
        (work / "app" / "__init__.py").write_text(f'__version__ = "{number}"\n')
        git(work, "add", ".")
        git(work, "commit", "-q", "-m", f"StationPlay {number}")
        commits[number] = git(work, "rev-parse", "HEAD")
        notes = work / "docs" / "releases" / f"v{number}.md"
        notes.write_text(f"---\ncommit: {commits[number]}\n---\n\nThe notes.\n")
        git(work, "add", ".")
        git(work, "commit", "-q", "-m", f"Release notes for {number}")
        git(work, "update-ref", "refs/remotes/origin/main", "HEAD")
        return commits[number]

    version("1.32.1")

    def go(**extra: str) -> tuple[str, int, str]:
        env = {
            **os.environ,
            "PATH": f"{bin_}:{os.environ['PATH']}",
            "LOG": str(log),
            "ASSETS": str(assets),
            "ARTIFACT": artifact,
            "RUNNER_TEMP": str(tmp_path / "temp"),
            "GITHUB_REPOSITORY": "egadgetboy/stationplay",
            "GITHUB_REPOSITORY_OWNER": "EgadgetBoy",
            "GH_TOKEN": "x",
            "FIRST_PUBLIC": "1.32.0",
            "FIRST_IMAGE": "1.34.0",
            "FIRST_SIGNED": "1.35.0",
            "GITHUB_ACTOR": "egadgetboy",
            **extra,
        }
        done = subprocess.run(
            ["bash", "-e", "-c", script()], cwd=work, env=env, capture_output=True, text=True
        )
        return (log.read_text() if log.exists() else ""), done.returncode, done.stdout

    go.assets = assets  # type: ignore[attr-defined]
    go.commits = commits  # type: ignore[attr-defined]
    go.version = version  # type: ignore[attr-defined]
    go.listed = listed  # type: ignore[attr-defined]
    go.temp = tmp_path / "temp"  # type: ignore[attr-defined]
    return go


def image_run(
    run, number: int, version: str = "1.32.1", status: str = "completed",
    test: str = "success", made: bool = True, image: bool = True,
) -> None:  # fmt: skip
    """Image run `number`, on that version's commit (newest first, as
    GitHub lists them: add the oldest first). From 1.34.0, with what its
    image job kept too (`image`): the joined image, by digest, and the
    arm64 image's package list."""
    runs = run.assets / "runs"
    before = runs.read_text() if runs.exists() else ""
    runs.write_text(f"{run.commits[version]} {number} {status}\n" + before)
    (run.assets / f"tested_{number}").write_text(test + "\n")
    if made:
        folder = run.assets / f"made_{number}"
        folder.mkdir()
        (folder / run.listed.replace("<version>", version)).write_text(
            f"StationPlay {version}: every package in the image that was tested\n"
        )
        if image:
            (folder / f"stationplay-{version}-image.txt").write_text(PINNED + "\n")
            (folder / f"stationplay-{version}-packages-arm64.txt").write_text(
                f"StationPlay {version}: every package in the arm64 image that was tested\n"
            )
    (run.assets / "manifest").write_text(MANIFEST)


def docker(said: str) -> list[str]:
    return [line for line in said.splitlines() if line.startswith("docker ")]


def creates(said: str) -> list[str]:
    return [line for line in said.splitlines() if line.startswith("gh release create")]


def test_a_tested_version_is_published_with_its_tested_package_list(run):
    image_run(run, 7)
    said, status, out = run()
    assert status == 0, said + out
    made = creates(said)
    assert len(made) == 1, said
    assert f"v1.32.1 --target {run.commits['1.32.1']}" in made[0]
    for name in (
        "stationplay-1.32.1.zip",
        "stationplay.yaml",
        "docker-compose.yml",
        "stationplay-1.32.1-packages.txt",
    ):
        assert f"/{name}" in made[0], made[0]
    assert "gh run download 7 --name" in said  # (a run that tested it)
    listed = run.temp / "v1.32.1" / "stationplay-1.32.1-packages.txt"
    assert listed.read_text() == "StationPlay 1.32.1: every package in the image that was tested\n"
    # (Source only: no image built, pushed or pulled, and no image's source.)
    assert not docker(said) and "ghcr" not in said and "gpl-source" not in said


def test_without_its_tested_package_list_nothing_is_published(run):
    image_run(run, 7, made=False)
    said, status, out = run()
    assert status == 1
    assert not creates(said)
    assert "has its list of packages" in out and "Re-run the newest of those runs" in out


def test_the_newest_passing_run_without_its_list_is_passed_over(run):
    """(A newer run on the same code that passed, but kept no list: one
    that did is used.)"""
    image_run(run, 7)
    image_run(run, 9, made=False)
    said, status, out = run()
    assert status == 0, said + out
    assert "gh run download 9" in said and "gh run download 7" in said
    assert len(creates(said)) == 1


def test_one_version_that_can_t_be_published_doesn_t_stop_the_next(run):
    run.version("1.32.2")
    image_run(run, 7, version="1.32.1", made=False)
    image_run(run, 8, version="1.32.2")
    said, status, _ = run()
    assert status == 1  # (1.32.1 refused, said on the run's page)
    made = creates(said)
    assert len(made) == 1 and made[0].startswith("gh release create v1.32.2 "), said
    assert "--latest=true" in made[0]


def test_a_version_whose_tests_failed_isn_t_published(run):
    image_run(run, 7, test="failure")
    said, status, out = run()
    assert status == 1
    assert not creates(said) and "run download" not in said
    assert "its tests didn't pass" in out


def test_a_version_still_being_tested_waits(run):
    image_run(run, 7, status="in_progress")
    said, status, out = run()
    assert status == 0
    assert not creates(said)
    assert "waits for its tests" in out


def test_a_published_release_is_left_alone(run):
    image_run(run, 7)
    (run.assets / "published").write_text("v1.32.0\nv1.32.1\n")
    said, status, out = run()
    assert status == 0, said + out
    assert not creates(said)
    assert "release upload" not in said and "run download" not in said and not docker(said)


def test_the_artifact_release_yml_asks_for_is_the_one_image_yml_keeps():
    """(The audit of 1.32.1: renaming one without the other would refuse
    every release, with every other test still passing.)"""
    name, listed = made_of()
    text = WORKFLOW.read_text()
    assert f'--name {name} --dir "$out/made-$run"' in text
    assert listed.replace("<version>", "$version") in text


# From 1.34.0: the image, the sources and the signature -------------------------------------

DIGEST = "sha256:" + hashlib.sha256(MANIFEST.encode()).hexdigest()
PINNED = f"ghcr.io/egadgetboy/stationplay@{DIGEST}"


def skopeo(said: str) -> list[str]:
    return [line for line in said.splitlines() if line.startswith("skopeo copy")]


def test_from_1_34_0_the_tested_image_gets_its_tags(run):
    run.version("1.34.0")
    image_run(run, 7, version="1.32.1", image=False)
    image_run(run, 8, version="1.34.0")
    said, status, out = run()
    assert status == 0, said + out
    # That very image (by digest), copied as it is, each tag checked.
    assert skopeo(said) == [
        f"skopeo copy --all --preserve-digests --quiet docker://{PINNED} "
        f"docker://ghcr.io/egadgetboy/stationplay:{tag}"
        for tag in ("1.34.0", "1.34", "latest")
    ]
    assert said.count("skopeo inspect --raw") == 3 and "docker build" not in said
    made = [line for line in creates(said) if line.startswith("gh release create v1.34.0 ")]
    assert len(made) == 1, said
    for name in ("stationplay-1.34.0-packages.txt", "stationplay-1.34.0-packages-arm64.txt",
                 "stationplay-1.34.0-source.tar", "stationplay-1.34.0.zip"):  # fmt: skip
        assert f"/{name}" in made[0], made[0]
    # The source, fetched in the tested image, with the arm64 image's list.
    [fetch] = [line for line in said.splitlines() if line.startswith("docker run")]
    assert PINNED in fetch and "--all --also /in/arm64.txt" in fetch and "--user 0" in fetch
    with tarfile.open(run.temp / "v1.34.0" / "stationplay-1.34.0-source.tar") as tar:
        assert "./ffmpeg_7.1.5-0+deb13u1.dsc" in tar.getnames()
    # (No key yet, before 1.35.0: published unsigned, and said.)
    assert ".zip.sig" not in made[0] and "zip isn't signed" in out
    # 1.32.1, before 1.34.0, as before: no image, no source.
    old = [line for line in creates(said) if line.startswith("gh release create v1.32.1 ")]
    assert len(old) == 1 and "source.tar" not in old[0] and "arm64" not in old[0]


def test_an_older_version_never_takes_the_newer_ones_tags(run):
    run.version("1.34.0")
    run.version("1.34.1")
    (run.assets / "published").write_text("v1.32.0\nv1.32.1\n")
    image_run(run, 8, version="1.34.0")
    image_run(run, 9, version="1.34.1")
    said, status, out = run()
    assert status == 0, said + out
    tags = [line.rsplit(":", 1)[1] for line in skopeo(said)]
    assert tags == ["1.34.0", "1.34.1", "1.34", "latest"]


def test_signed_with_the_key_and_checked(run):
    run.version("1.35.0")
    (run.assets / "published").write_text("v1.32.0\nv1.32.1\n")
    image_run(run, 8, version="1.35.0")
    said, status, out = run(SIGNING_KEY="-----BEGIN OPENSSH PRIVATE KEY-----\nx\n")
    assert status == 0, said + out
    assert "ssh-keygen -Y sign -q -f" in said and "-n stationplay-release" in said
    assert "ssh-keygen -Y verify -f" in said and "-I stationplay-release" in said
    [made] = creates(said)
    assert "/stationplay-1.35.0.zip.sig" in made
    # (The key is gone once it's done.)
    assert not (run.temp / "signing-key").exists()


def test_from_1_35_0_an_unsigned_zip_isn_t_published(run):
    run.version("1.35.0")
    (run.assets / "published").write_text("v1.32.0\nv1.32.1\n")
    image_run(run, 8, version="1.35.0")
    said, status, out = run()
    assert status == 1 and not creates(said) and not skopeo(said)
    assert "couldn't be signed" in out
    (run.assets / "key_wont_do").write_text("")
    said, status, out = run(SIGNING_KEY="a key with a passphrase")
    assert status == 1 and not creates(said) and "couldn't be signed" in out


def test_an_image_that_isn_t_the_tested_one_stops_it(run):
    run.version("1.34.0")
    (run.assets / "published").write_text("v1.32.0\nv1.32.1\n")
    image_run(run, 8, version="1.34.0")
    (run.assets / "manifest").write_text("something else\n")
    said, status, out = run()
    assert status == 1 and not creates(said)
    assert "isn't the image that was tested" in out


def test_without_its_image_or_its_sources_nothing_is_published(run):
    run.version("1.34.0")
    (run.assets / "published").write_text("v1.32.0\nv1.32.1\n")
    image_run(run, 8, version="1.34.0", image=False)
    said, status, out = run()
    assert status == 1 and not creates(said) and "kept no image" in out
    image_run(run, 9, version="1.34.0")
    (run.assets / "no_source").write_text("")
    said, status, out = run()
    assert status == 1 and not creates(said) and not skopeo(said)
    assert "GPL and LGPL packages couldn't all be fetched" in out
