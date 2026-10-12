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
