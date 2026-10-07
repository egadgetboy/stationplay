"""Settings, read once from environment variables.

Everything has a sensible default except the Plex URL and token.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _picture(height: str) -> str:
    """The picture size nearest a VIDEO_HEIGHT given ("" if none is)."""
    try:
        lines = int(height)
    except ValueError:
        return ""
    return "480p" if lines <= 600 else "1080p" if lines >= 900 else "720p"


def _path_mappings(raw: str) -> list[tuple[str, str]]:
    """Parse "plex/path:local/path;other:other2" into pairs.

    Plex reports file paths as Plex sees them. When this app sees the same
    files under a different path, a mapping translates between the two.
    """
    pairs: list[tuple[str, str]] = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        src, dst = chunk.split(":", 1)
        pairs.append((src.rstrip("/"), dst.rstrip("/")))
    return pairs


@dataclass
class Settings:
    plex_url: str = ""
    plex_token: str = ""
    data_dir: Path = Path("/data")
    port: int = 3310
    # The port the internet reaches StationPlay's page on, through a tunnel or
    # reverse proxy (0: none). See access.py: Plex's addresses aren't on it.
    public_port: int = 0
    # Advertised address for Plex. Normally worked out from the request,
    # so this only needs setting behind unusual proxies.
    base_url: str = ""
    friendly_name: str = "StationPlay"
    # Settings older versions read from the environment, now set on the page
    # (see playback.py), which start from them if they're given: TUNER_COUNT
    # (0: not given), and the picture size VIDEO_HEIGHT said ("" if not).
    tuner_count: int = 0
    picture: str = ""
    path_mappings: list[tuple[str, str]] = field(default_factory=list)
    # Where the media library is mounted inside this container. Paths Plex
    # reports are matched against it automatically.
    media_dir: str = "/media"
    # Video encoding: auto (use a GPU if one works, else CPU), nvidia,
    # intel/amd (VA-API), or cpu.
    hw_accel: str = "auto"
    # Optional: a specific render node (/dev/dri/renderD129) or NVIDIA GPU index.
    hw_device: str = ""
    preferred_audio_language: str = "eng"
    # The standard (720p) picture, from which each station's is worked out
    # (ff.sized): every program on it is converted to that.
    video_width: int = 1280
    video_height: int = 720
    video_bitrate_kbps: int = 3500
    audio_bitrate_kbps: int = 192
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    # How long a channel keeps running after the last viewer leaves, so
    # flipping back to it is instant.
    idle_grace_seconds: int = 20

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            plex_url=os.environ.get("PLEX_URL", "").rstrip("/"),
            plex_token=os.environ.get("PLEX_TOKEN", ""),
            data_dir=Path(os.environ.get("DATA_DIR", "/data")),
            port=_int("PORT", 3310),
            public_port=_int("PUBLIC_PORT", 0),
            base_url=os.environ.get("BASE_URL", "").rstrip("/"),
            friendly_name=os.environ.get("FRIENDLY_NAME", "StationPlay"),
            tuner_count=_int("TUNER_COUNT", 0),
            picture=_picture(os.environ.get("VIDEO_HEIGHT", "")),
            path_mappings=_path_mappings(os.environ.get("PATH_MAPPINGS", "")),
            media_dir=os.environ.get("MEDIA_DIR", "/media"),
            hw_accel=os.environ.get("HW_ACCEL", "auto"),
            hw_device=os.environ.get("HW_DEVICE", ""),
            preferred_audio_language=os.environ.get("AUDIO_LANGUAGE", "eng"),
            audio_bitrate_kbps=_int("AUDIO_BITRATE_KBPS", 192),
            ffmpeg_path=os.environ.get("FFMPEG_PATH", "ffmpeg"),
            ffprobe_path=os.environ.get("FFPROBE_PATH", "ffprobe"),
            idle_grace_seconds=_int("IDLE_GRACE_SECONDS", 20),
        )

    def map_path(self, plex_path: str) -> str:
        for src, dst in self.path_mappings:
            if plex_path == src or plex_path.startswith(src + "/"):
                return dst + plex_path[len(src) :]
        return plex_path
