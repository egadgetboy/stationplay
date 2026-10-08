"""Choosing and supervising GPU encoding.

At startup, StationPlay looks for a usable GPU (NVIDIA first, then Intel or
AMD via VA-API) and proves it works by encoding a short test clip with the
exact command a real program uses. Until that test passes, and whenever the
GPU misbehaves, everything is encoded on the CPU instead. A GPU problem
never takes a channel off the air and never marks a file as broken.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field

from . import ffmpeg as ff
from .config import Settings
from .ffmpeg import CPU, Encoder

log = logging.getLogger(__name__)

# After this many programs in a row fail on the GPU but play fine on the
# CPU, the GPU is switched off until StationPlay restarts.
GPU_STRIKES_LIMIT = 3
# After this many copies for StationPlay's apps in a row fail on the GPU but
# are made fine on the CPU, copies are converted on the CPU until StationPlay
# restarts. The stations keep the GPU: a copy's trouble there (a GPU that
# runs out of sessions, say) never takes it from them.
COPY_STRIKES_LIMIT = 3
SELF_TEST_SECONDS = 2.0

MODES = {
    "auto": ("nvidia", "vaapi"),
    "gpu": ("nvidia", "vaapi"),
    "nvidia": ("nvidia",),
    "nvenc": ("nvidia",),
    "intel": ("vaapi",),
    "amd": ("vaapi",),
    "vaapi": ("vaapi",),
    "qsv": ("vaapi",),
    "cpu": (),
    "none": (),
    "off": (),
}


def find_candidates(settings: Settings) -> tuple[list[Encoder], list[str]]:
    """GPUs visible to this container, best first, plus notes on anything
    that's present but can't be used."""
    mode = settings.hw_accel.lower().strip()
    kinds = MODES.get(mode, MODES["auto"])
    candidates: list[Encoder] = []
    notes: list[str] = []
    for kind in kinds:
        if kind == "nvidia":
            if os.path.exists("/dev/nvidiactl") or glob.glob("/dev/nvidia[0-9]*"):
                candidates.append(Encoder("nvidia", settings.hw_device or None))
            elif mode in ("nvidia", "nvenc"):
                notes.append(
                    "StationPlay can't see an NVIDIA GPU. See the NVIDIA section of the README."
                )
        elif kind == "vaapi":
            nodes = (
                [settings.hw_device]
                if settings.hw_device
                else sorted(glob.glob("/dev/dri/renderD*"))
            )
            if not nodes:
                if mode not in ("auto", "gpu"):
                    notes.append(
                        "StationPlay can't see an Intel or AMD GPU because /dev/dri isn't "
                        "passed to its container."
                    )
                continue
            for node in nodes:
                if os.access(node, os.R_OK | os.W_OK):
                    candidates.append(Encoder("vaapi", node))
                else:
                    notes.append(_permission_note(node))
    return candidates, notes


def _permission_note(node: str) -> str:
    try:
        gid = os.stat(node).st_gid
    except OSError:
        return f"StationPlay can't access {node}."
    return (
        f"StationPlay isn't allowed to use {node}, which belongs to group {gid}. "
        f'Add "{gid}" under group_add in the app\'s YAML.'
    )


async def _run(args: list[str], timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "timed out"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def self_test(settings: Settings, encoder: Encoder, clip: str) -> str | None:
    """Encodes a couple of seconds of `clip` exactly as a real program would.

    Returns None if the encoder works, otherwise a short reason.
    """
    args = ff.program_command(
        settings, clip, 0.0, SELF_TEST_SECONDS, 10.0, SELF_TEST_SECONDS, 0, "test", encoder
    )
    args[args.index("pipe:1")] = "-"
    code, _out, err = await _run(args, timeout=45)
    progress = ff.Progress()
    messages = []
    for line in err.splitlines():
        message = ff.parse_progress_line(line, progress)
        if message:
            messages.append(message)
    if code == 0 and progress.frames >= 10:
        return None
    detail = messages[-1] if messages else f"exit code {code}"
    return ff.redact(detail)[:300]


async def make_test_clip(settings: Settings, directory: str) -> str:
    """A tiny H.264 clip with audio, made on the CPU, to test GPUs against."""
    path = os.path.join(directory, "gpu-test.mkv")
    args = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=640x360:r=30000/1001",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:sample_rate=48000",
        "-t",
        "3",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        path,
    ]
    code, _, err = await _run(args, timeout=60)
    if code != 0:
        raise RuntimeError(f"couldn't make the GPU test video ({err.strip()[-200:]})")
    return path


@dataclass
class GpuManager:
    settings: Settings
    active: Encoder = CPU
    state: str = "starting"  # starting | gpu | cpu | disabled
    note: str = ""
    tested: list[dict] = field(default_factory=list)
    strikes: int = 0
    copy_strikes: int = 0
    copies_off: bool = False  # (copies on the CPU: see COPY_STRIKES_LIMIT)
    gpu_failures: int = 0
    cpu_rescues: int = 0
    _task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.detect())

    async def wait_ready(self) -> None:
        if self._task is not None:
            await asyncio.shield(self._task)

    async def detect(self) -> None:
        mode = self.settings.hw_accel.lower().strip()
        if mode not in MODES:
            log.warning("Unknown HW_ACCEL %r; treating it as auto", self.settings.hw_accel)
        candidates, notes = find_candidates(self.settings)
        if not candidates:
            self._use_cpu(
                " ".join(notes)
                or (
                    "GPU encoding is turned off (HW_ACCEL=cpu)."
                    if MODES.get(mode) == ()
                    else "StationPlay can't see a GPU."
                )
            )
            return
        workdir = tempfile.mkdtemp(prefix="stationplay-gpu-")
        try:
            clip = await make_test_clip(self.settings, workdir)
            for encoder in candidates:
                started = time.monotonic()
                problem = await self_test(self.settings, encoder, clip)
                self.tested.append(
                    {
                        "encoder": encoder.label,
                        "ok": problem is None,
                        "problem": problem,
                        "seconds": round(time.monotonic() - started, 1),
                    }
                )
                if problem is None:
                    self.active = encoder
                    self.state = "gpu"
                    self.note = ""
                    log.info("Encoding video on %s", encoder.label)
                    return
                log.warning("%s failed its encoding test (%s)", encoder.label, problem)
                notes.append(f"{encoder.label} failed its encoding test ({problem.rstrip('.')}).")
            self._use_cpu(" ".join(notes))
        except Exception as e:  # never let GPU detection break startup
            log.exception("GPU detection failed")
            self._use_cpu(f"GPU detection failed: {e}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _use_cpu(self, note: str) -> None:
        self.active = CPU
        self.state = "cpu"
        self.note = note
        log.info("Encoding video on the CPU. %s", note)

    def encoder_for(self, cpu_only: bool) -> Encoder:
        return CPU if cpu_only else self.active

    def encoder_for_copies(self) -> Encoder:
        """Where a copy's picture is converted (see converting.py)."""
        return CPU if self.copies_off else self.active

    # Called by stations as programs play, and by copies as they're made -----

    def gpu_failed(self, reason: str, stalled: bool = False, what: str = "that program") -> None:
        """`what`: what carries on on the CPU, as the log names it."""
        self.gpu_failures += 1
        if stalled:
            # (The disk as likely as the GPU: a read held up stalls it too.)
            log.warning("Playback stalled on the GPU (%s); continuing %s on the CPU", reason, what)
        else:
            log.warning("GPU encoding failed (%s); continuing %s on the CPU", reason, what)

    def cpu_rescued(self) -> None:
        """A program that failed on the GPU played fine on the CPU."""
        self.cpu_rescues += 1
        self.strikes += 1
        if self.strikes >= GPU_STRIKES_LIMIT and self.state == "gpu":
            self.state = "disabled"
            self.note = (
                f"{self.active.label} was turned off after {self.strikes} programs in a row "
                "failed on it but played fine on the CPU. Restart StationPlay to try it again."
            )
            log.error(self.note)
            self.active = CPU

    def gpu_succeeded(self) -> None:
        self.strikes = 0

    # Called by copies as they're made (see converting.py) -------------------

    def copy_rescued(self) -> None:
        """A copy that failed on the GPU was made fine on the CPU."""
        self.cpu_rescues += 1
        self.copy_strikes += 1
        if self.copy_strikes >= COPY_STRIKES_LIMIT and not self.copies_off and self.active.is_gpu:
            self.copies_off = True
            log.error(
                "Copies for StationPlay's apps are converted on the CPU from now on: %d in a "
                "row failed on %s but were made fine on the CPU. Stations keep using it. "
                "Restart StationPlay to try it again.",
                self.copy_strikes,
                self.active.label,
            )

    def copy_succeeded(self) -> None:
        self.copy_strikes = 0

    def as_dict(self) -> dict:
        return {
            "requested": self.settings.hw_accel,
            "state": self.state,
            "active": self.active.label,
            "note": self.note,
            "tested": self.tested,
            "gpuFailures": self.gpu_failures,
            "cpuRescues": self.cpu_rescues,
            "copiesOnCpu": self.copies_off,
        }
