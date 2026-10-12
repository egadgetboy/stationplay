"""The list of every package in the image that each release carries
(tools/sbom.py): each Debian package at its exact version, with where its
source is kept, and each Python package with its license."""

from __future__ import annotations

import sys
from email.message import Message
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
try:
    import sbom
finally:
    sys.path.pop(0)

LISTING = (
    "ii \tlibavcodec61\t7:7.1.5-0+deb13u1\tffmpeg\t7:7.1.5-0+deb13u1\n"
    "ii \tbash\t5.2.37-2\t\t\n"  # (built from a source package of its own name)
    "rc \tgone\t1.0\tgone\t1.0\n"  # (removed: not in the image)
    "ii \tlibx264-164\t2:0.164.3108+git31e19f9-2+b1\tx264\t2:0.164.3108+git31e19f9-2\n"
)


class Dist:
    def __init__(self, name: str, version: str, **fields: str | list[str]) -> None:
        self.version = version
        self.metadata = Message()
        self.metadata["Name"] = name
        for key, value in fields.items():
            for each in value if isinstance(value, list) else [value]:
                self.metadata[key.replace("_", "-")] = each


def test_debian_packages_with_their_source_and_where_it_s_kept():
    rows = sbom.debian_rows(LISTING)
    assert rows == [
        ("bash", "5.2.37-2", "bash", "5.2.37-2"),
        ("libavcodec61", "7:7.1.5-0+deb13u1", "ffmpeg", "7:7.1.5-0+deb13u1"),
        ("libx264-164", "2:0.164.3108+git31e19f9-2+b1", "x264", "2:0.164.3108+git31e19f9-2"),
    ]
    assert sbom.snapshot("ffmpeg", "7:7.1.5-0+deb13u1") == (
        "https://snapshot.debian.org/package/ffmpeg/7%3A7.1.5-0%2Bdeb13u1/"
    )


def test_python_packages_each_once_with_a_license():
    rows = sbom.python_rows([
        Dist("fastapi", "0.115.0", License_Expression="MIT"),
        Dist("Jinja2", "3.1.4", License="BSD License\nlong text after"),
        Dist("odd", "1.0", License="x" * 200, Classifier=["License :: OSI Approved :: MIT License"]),
        Dist("bare", "2.0"),
        Dist("FastAPI", "0.115.0"),  # (the same one, found twice)
    ])  # fmt: skip
    assert rows == [
        ("bare", "2.0", "see its page"),
        ("fastapi", "0.115.0", "MIT"),
        ("Jinja2", "3.1.4", "BSD License"),
        ("odd", "1.0", "MIT License"),
    ]


def test_the_list_names_every_package_and_the_release_s_files():
    text = sbom.report(
        "1.32.1",
        sbom.debian_rows(LISTING),
        [("fastapi", "0.115.0", "MIT")],
        "3.13.16",
    )
    assert text.startswith("StationPlay 1.32.1: every package in its image\n")
    assert "Debian packages (3)" in text and "Python packages (1)" in text
    assert (
        "libavcodec61 7:7.1.5-0+deb13u1: source ffmpeg 7:7.1.5-0+deb13u1, "
        "https://snapshot.debian.org/package/ffmpeg/7%3A7.1.5-0%2Bdeb13u1/"
    ) in text
    assert "fastapi 0.115.0: MIT, https://pypi.org/project/fastapi/0.115.0/" in text
    assert "stationplay-1.32.1-gpl-source.tar" in text and "stationplay-1.32.1.zip" in text
    # (The audit of 1.32.1: Python itself is in neither dpkg's list nor pip's.)
    assert (
        "Python 3.13.16 (the python image's own, under the PSF license), "
        "https://www.python.org/ftp/python/3.13.16/Python-3.13.16.tgz"
    ) in text
