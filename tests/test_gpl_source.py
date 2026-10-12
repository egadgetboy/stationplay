"""The source of FFmpeg, x264 and x265 that each release carries
(tools/gpl_source.py): the versions in the image, and each file checked as
Debian's .dsc and snapshot.debian.org say, so an older image's source can
still be found once Debian's archive has moved on (the audit of 1.32.1)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
try:
    import gpl_source
finally:
    sys.path.pop(0)

TARBALL = b"the source itself"
DSC = f"""\
Format: 3.0 (quilt)
Source: x264
Version: 2:0.164.3108+git31e19f9-2
Checksums-Sha1:
 {hashlib.sha1(TARBALL).hexdigest()} {len(TARBALL)} x264_0.164.orig.tar.gz
Checksums-Sha256:
 {hashlib.sha256(TARBALL).hexdigest()} {len(TARBALL)} x264_0.164.orig.tar.gz
Files:
 abc {len(TARBALL)} x264_0.164.orig.tar.gz
"""


def test_the_versions_in_the_image():
    listing = (
        "ffmpeg 7:7.1.5-0+deb13u1\n"
        "ffmpeg 7:7.1.5-0+deb13u1\n"
        "x264 2:0.164.3108+git31e19f9-2\n"
        "odd line here\n"
    )
    assert gpl_source.installed_versions(listing) == {
        "ffmpeg": "7:7.1.5-0+deb13u1",
        "x264": "2:0.164.3108+git31e19f9-2",
    }


def test_snapshot_s_files_with_the_dsc_first():
    tar, dsc = "a" * 40, "b" * 40
    answer = {
        "result": [{"hash": tar}, {"hash": dsc}, {"hash": "not-a-hash"}],
        "fileinfo": {
            tar: [{"name": "x264_0.164.orig.tar.gz", "archive_name": "debian"}],
            dsc: [{"name": "x264_0.164-2.dsc"}],
            "not-a-hash": [{"name": "../../etc/passwd"}],
        },
    }
    assert gpl_source.snapshot_files(answer) == [
        ("x264_0.164-2.dsc", dsc),
        ("x264_0.164.orig.tar.gz", tar),
    ]


def test_each_file_is_as_the_dsc_says(tmp_path):
    (tmp_path / "x264.dsc").write_text(DSC)
    assert gpl_source.dsc_sha256(DSC) == {
        "x264_0.164.orig.tar.gz": hashlib.sha256(TARBALL).hexdigest()
    }
    (tmp_path / "x264_0.164.orig.tar.gz").write_bytes(TARBALL)
    gpl_source.check(tmp_path, "x264.dsc")
    (tmp_path / "x264_0.164.orig.tar.gz").write_bytes(b"something else")
    with pytest.raises(ValueError, match=r"isn't as x264\.dsc says"):
        gpl_source.check(tmp_path, "x264.dsc")
    (tmp_path / "x264_0.164.orig.tar.gz").unlink()
    with pytest.raises(ValueError):
        gpl_source.check(tmp_path, "x264.dsc")


def test_a_file_from_snapshot_is_checked_against_its_hash(tmp_path, monkeypatch):
    dsc_hash = hashlib.sha1(DSC.encode()).hexdigest()
    tar_hash = hashlib.sha1(TARBALL).hexdigest()
    served = {
        "srcfiles": json.dumps(
            {
                "result": [{"hash": dsc_hash}, {"hash": tar_hash}],
                "fileinfo": {
                    dsc_hash: [{"name": "x264.dsc"}],
                    tar_hash: [{"name": "x264_0.164.orig.tar.gz"}],
                },
            }
        ).encode(),
        dsc_hash: DSC.encode(),
        tar_hash: TARBALL,
    }

    def get(url: str) -> bytes:
        assert url.startswith("https://snapshot.debian.org/")
        if "/mr/package/x264/2%3A0.164.3108%2Bgit31e19f9-2/srcfiles" in url:
            return served["srcfiles"]
        return served[url.rsplit("/", 1)[1]]

    monkeypatch.setattr(gpl_source, "_get", get)
    gpl_source.from_snapshot("x264", "2:0.164.3108+git31e19f9-2", tmp_path)
    assert (tmp_path / "x264_0.164.orig.tar.gz").read_bytes() == TARBALL
    # A file that isn't what snapshot's hash says stops it.
    served[tar_hash] = b"tampered"
    with pytest.raises(ValueError, match="isn't as it should be"):
        gpl_source.from_snapshot("x264", "2:0.164.3108+git31e19f9-2", tmp_path)


def test_every_gpl_and_lgpl_package_s_source_is_wanted():
    """(From 1.34.0, when the image is published: C6.) Each source package
    an installed package with the GPL, LGPL or AGPL in its copyright file is
    built from, once; one without a copyright file too; others not."""
    listing = (
        "libavcodec61 ffmpeg 7:7.1.5-0+deb13u1\n"
        "libavformat61 ffmpeg 7:7.1.5-0+deb13u1\n"
        "libc6 glibc 2.41-12\n"
        "bash bash 5.2.37-2\n"
        "libssl3t64 openssl 3.5.1-1\n"
        "mystery mystery 1.0-1\n"
        "odd line\n"
    )
    copyrights = {
        "libavcodec61": "License: LGPL-2.1+\n",
        "libavformat61": "License: LGPL-2.1+\n",
        "libc6": "the GNU Lesser General Public License, version 2.1\n",
        "bash": "License: GPL-3+\n",
        "libssl3t64": "License: Apache-2.0\n",
    }
    found = gpl_source.gpl_sources(listing, copyrights.get)
    assert found == {
        "ffmpeg": "7:7.1.5-0+deb13u1", "glibc": "2.41-12", "bash": "5.2.37-2",
        "mystery": "1.0-1",
    }  # fmt: skip


def test_another_image_s_packages_add_their_own_sources():
    listed = (
        "tapiOca 1.34.0: every package in the image that was tested\n"
        "bash 5.2.37-2: source bash 5.2.37-2, https://snapshot.debian.org/package/bash/5.2.37-2/\n"
        "libarmonly1 1.0-1: source armonly 1.0-1, https://snapshot.debian.org/package/armonly/1.0-1/\n"
        "fastapi 0.115.0: MIT, https://pypi.org/project/fastapi/0.115.0/\n"
    )
    assert gpl_source.listed_sources(listed, {("bash", "5.2.37-2")}) == {("armonly", "1.0-1")}


def test_another_image_s_package_at_another_version_adds_its_source():
    """(The audit of 1.34.0: a package installed here, but at another
    version in the arm64 image, was taken as the same, and its source left
    out.)"""
    listed = (
        "bash 5.2.37-3: source bash 5.2.37-3, https://snapshot.debian.org/package/bash/5.2.37-3/\n"
        "libc6 2.41-12: source glibc 2.41-12, https://snapshot.debian.org/package/glibc/2.41-12/\n"
    )
    installed = {("bash", "5.2.37-2"), ("libc6", "2.41-12")}
    assert gpl_source.listed_sources(listed, installed) == {("bash", "5.2.37-3")}


def test_both_versions_of_a_source_are_fetched(monkeypatch, tmp_path):
    """--all with --also: a source in both images at different versions is
    fetched at each."""
    answers = {
        "${Package} ${source:Package} ${source:Version}\n": "bash bash 5.2.37-2\n",
        "${Package} ${Version}\n": "bash 5.2.37-2\n",
    }

    def dpkg(command, **kwargs):
        class Done:
            stdout = answers[command[-1]]

        return Done()

    monkeypatch.setattr(gpl_source.subprocess, "run", dpkg)
    monkeypatch.setattr(gpl_source, "_copyright", lambda package: "License: GPL-3+\n")
    arm64 = tmp_path / "arm64.txt"
    arm64.write_text(
        "bash 5.2.37-3: source bash 5.2.37-3, https://snapshot.debian.org/package/bash/5.2.37-3/\n"
    )
    assert gpl_source.wanted(["--all", "--also", str(arm64)]) == [
        ("bash", "5.2.37-2"), ("bash", "5.2.37-3")
    ]  # fmt: skip


def test_a_dsc_is_named_without_the_epoch():
    assert gpl_source._dsc_name("ffmpeg", "7:7.1.5-0+deb13u1") == "ffmpeg_7.1.5-0+deb13u1.dsc"
    assert gpl_source._dsc_name("bash", "5.2.37-2") == "bash_5.2.37-2.dsc"


def test_without_all_only_ffmpeg_x264_and_x265(monkeypatch):
    def dpkg(*args, **kwargs):
        class Done:
            stdout = "ffmpeg 7:7.1.5-0+deb13u1\nx264 2:0.164-2\nx265 4.1-2\nbash 5.2-2\n"

        return Done()

    monkeypatch.setattr(gpl_source.subprocess, "run", dpkg)
    assert gpl_source.wanted([]) == [
        ("ffmpeg", "7:7.1.5-0+deb13u1"), ("x264", "2:0.164-2"), ("x265", "4.1-2")
    ]  # fmt: skip
    assert gpl_source.wanted(["--all", "--also"]) == "--also needs a package list"
