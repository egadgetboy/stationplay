"""The quick image check (tools/image_check.py): it lays a project out as
its image's test stage has it, as Docker does, so a test reading a file the
image hasn't got fails in minutes, not 40 minutes into the image workflow
(as 1.32.0's first image run did)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
try:
    import image_check
finally:
    sys.path.pop(0)

DOCKERFILE = """\
FROM python:3.13-slim AS stationplay
WORKDIR /opt/stationplay
COPY requirements.txt .
COPY app ./app
COPY LICENSE NOTICES.md ./
COPY --from=builder /x /y

FROM stationplay AS test
COPY pytest.ini Dockerfile \\
     ./
COPY docs ./docs
COPY tools/one.py ./tools/
COPY tools/logos/letters.py ./tools/logos/
COPY tests ./tests

FROM stationplay
"""

IGNORE = """\
__pycache__/
*.ts
data/
# (only these tools are for the tests)
tools/*
!tools/one.py
!tools/logos/letters.py
"""


def project(root: Path) -> Path:
    files = {
        "Dockerfile": DOCKERFILE,
        ".dockerignore": IGNORE,
        "requirements.txt": "fastapi\n",
        "pytest.ini": "[pytest]\n",
        "LICENSE": "AGPL\n",
        "NOTICES.md": "notices\n",
        "README.md": "not in the image\n",
        "a.ts": "left out at the top\n",
        "app/main.py": "x = 1\n",
        "app/web/a.ts": "kept: *.ts is only the top folder's\n",
        "app/__pycache__/main.cpython-313.pyc": "",
        "docs/api.md": "api\n",
        "tools/one.py": "one\n",
        "tools/two.py": "not in the image\n",
        "tools/logos/letters.py": "letters\n",
        "tools/logos/kit.py": "not in the image\n",
        "tests/test_a.py": "def test_a():\n    pass\n",
        "data/stationplay.db": "",
    }
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


def test_each_stage_has_its_copies_and_its_bases(tmp_path):
    stages = image_check.stages(DOCKERFILE)
    assert stages["stationplay"] == [
        (["requirements.txt"], "."),
        (["app"], "./app"),
        (["LICENSE", "NOTICES.md"], "./"),
    ]  # (not the copy from another stage)
    assert stages["test"][0] == (["pytest.ini", "Dockerfile"], "./")
    test = image_check.copies_for(DOCKERFILE, "test")
    assert test[:3] == stages["stationplay"] and test[3:] == stages["test"]


def test_dockerignore_works_as_docker_s_does():
    rules = image_check._parse_ignore(IGNORE)
    assert image_check.ignored(rules, "tools/two.py")
    assert not image_check.ignored(rules, "tools/one.py")
    assert image_check.ignored(rules, "tools/logos/kit.py")
    assert not image_check.ignored(rules, "tools/logos/letters.py")
    assert image_check.ignored(rules, "data/stationplay.db")
    assert image_check.ignored(rules, "a.ts") and not image_check.ignored(rules, "app/web/a.ts")
    assert not image_check.ignored(rules, "docs/api.md")


def test_a_project_is_laid_out_as_its_image_has_it(tmp_path):
    root = project(tmp_path / "project")
    into = tmp_path / "image"
    laid = image_check.lay_out(root, into)
    assert sorted(laid) == [
        "Dockerfile", "LICENSE", "NOTICES.md", "app/main.py", "app/web/a.ts", "docs/api.md",
        "pytest.ini", "requirements.txt", "tests/test_a.py", "tools/logos/letters.py",
        "tools/one.py",
    ]  # fmt: skip
    assert (into / "tools" / "one.py").read_text() == "one\n"
    assert not (into / "README.md").exists() and not (into / "tools" / "two.py").exists()


def test_the_tests_it_runs_are_those_reaching_outside_their_folder(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_inside.py").write_text("FAKE = Path(__file__).with_name('x.py')\n")
    (tests / "test_root.py").write_text("ROOT = Path(__file__).resolve().parent.parent\n")
    (tests / "test_tools.py").write_text("sys.path.insert(0, str(Path(__file__).parents[1]))\n")
    (tests / "helper.py").write_text("ROOT = Path(__file__).parents[1]\n")
    assert image_check.reaching_out(tests) == ["tests/test_root.py", "tests/test_tools.py"]


def test_stationplay_s_own_check_runs_this_file_too():
    """(This file reads tools/, so the image's test stage must have it.)"""
    here = Path(__file__)
    assert f"tests/{here.name}" in image_check.reaching_out(here.parent)


def test_a_file_git_hasn_t_got_isn_t_laid_out(tmp_path):
    """The audit of 1.32.1: the check copied the working folder, so a file a
    test reads that was never added to git passed here and failed in the
    image workflow, whose checkout hasn't got it."""
    root = project(tmp_path / "project")
    every = image_check.lay_out(root, tmp_path / "all")
    added = {"Dockerfile", "requirements.txt", "app/main.py", "tests/test_a.py"}
    some = image_check.lay_out(root, tmp_path / "some", only=added)
    assert "docs/api.md" in every and "docs/api.md" not in some
    assert sorted(some) == ["Dockerfile", "app/main.py", "requirements.txt", "tests/test_a.py"]
    assert image_check.tracked(tmp_path / "not-a-checkout") is None


def test_other_ways_of_reaching_outside_count_too(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_dirname.py").write_text("HERE = os.path.dirname(os.path.dirname(__file__))\n")
    (tests / "test_dots.py").write_text('DOCS = HERE / ".." / "docs"\n')
    (tests / "test_attack.py").write_text('BAD = {"ratingKey": "../../accounts"}\n')
    assert image_check.reaching_out(tests) == ["tests/test_dirname.py", "tests/test_dots.py"]


def test_git_is_the_tests_own():
    """git, which one test needs, goes in the tests' stage only, never in
    the image people build (the audit of 1.32.1: nothing kept it there)."""
    text = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    stages = re.split(r"(?m)^FROM ", text.replace("\\\n", " "))[1:]
    with_git = [
        stage.split("\n", 1)[0].strip()
        for stage in stages
        if any(
            "apt-get install" in line and "git" in line.split()
            for line in stage.splitlines()
            if line.startswith("RUN ")
        )
    ]
    assert with_git == ["stationplay AS test"]
