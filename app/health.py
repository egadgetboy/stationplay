"""The server's health, now, for the Stats tab (Admins only): the processor
and memory StationPlay uses and the whole machine's, what it's sending and
receiving, and the data folder's free space; with the last HISTORY_S of
each, kept in memory only.

It's read from Linux's own files (/proc, and the cgroup files Docker gives
a container), every SAMPLE_S: a few small files, cheap enough to read
whether or not anyone's looking. Anything that isn't there (another system,
a container that hides it) is None: the Stats tab says "not available"
for it.

StationPlay's own use is its container's (its cgroup: StationPlay and the
ffmpegs it runs), or this process's alone where there's no cgroup to read.
Memory used is the cgroup's, less what the kernel can drop at once (files
it has read lately), as `docker stats` counts it. The machine's memory is
the container's limit, when it has one, rather than the machine's.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SAMPLE_S = 5.0
HISTORY_S = 600.0
# A memory limit at least this big is no limit (cgroup v1 says "no limit"
# with a number this size).
NO_LIMIT = 1 << 60


@dataclass
class Sample:
    """One look at the server: each value None where it couldn't be read."""

    at_ms: int
    own_cpu: float | None = None  # StationPlay's share of the machine's processors, in %
    cpu: float | None = None  # the whole machine's, in %
    own_memory: int | None = None  # bytes
    memory_used: int | None = None  # the machine's (or within the container's limit)
    memory_total: int | None = None
    memory_limit: bool = False  # (memory_total is the container's limit)
    sending: float | None = None  # Mbps
    receiving: float | None = None
    free: int | None = None  # the data folder's, in bytes
    disk: int | None = None
    on_gpu: int = 0  # stations and copies on the GPU


@dataclass
class _Counters:
    """What rates are worked out from, between one look and the next."""

    at: float  # time.monotonic()
    busy: int | None = None  # the machine's processor time, in ticks
    total: int | None = None
    own_s: float | None = None  # StationPlay's processor time, in seconds
    received: int | None = None  # bytes
    sent: int | None = None


class Health:
    def __init__(
        self,
        data_dir: Path,
        proc: Path = Path("/proc"),
        cgroup: Path = Path("/sys/fs/cgroup"),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.data_dir = data_dir
        self.proc = proc
        self.cgroup = cgroup
        self.clock = clock
        self.processors = 0
        self.history: deque[Sample] = deque(maxlen=round(HISTORY_S / SAMPLE_S))
        self._last: _Counters | None = None
        self._folders: dict[str, list[Path]] = {}

    # Looking --------------------------------------------------------------

    def sample(self, on_gpu: int = 0) -> Sample:
        """Reads everything once, and keeps it (rates are since the last
        look: the first has none)."""
        now = _Counters(self.clock())
        out = Sample(int(time.time() * 1000), on_gpu=on_gpu)
        stat = self._read("stat")
        if stat is not None:
            now.busy, now.total, self.processors = _processor(stat)
        now.own_s = self._own_cpu_s()
        net = self._read("net/dev")
        if net is not None:
            now.received, now.sent = _network(net)
        last = self._last
        if last is not None and now.at > last.at:
            out.cpu = _share(now.busy, last.busy, now.total, last.total)
            processors = self.processors or os.cpu_count() or 1
            if now.own_s is not None and last.own_s is not None:
                spent = max(0.0, now.own_s - last.own_s)
                out.own_cpu = round(min(100.0, spent / ((now.at - last.at) * processors) * 100), 1)
            out.receiving = _rate(now.received, last.received, now.at - last.at)
            out.sending = _rate(now.sent, last.sent, now.at - last.at)
        self._last = now
        out.own_memory = self._own_memory()
        out.memory_used, out.memory_total, out.memory_limit = self._memory(out.own_memory)
        with contextlib.suppress(OSError):
            disk = shutil.disk_usage(self.data_dir)
            out.free, out.disk = disk.free, disk.total
        self.history.append(out)
        return out

    async def run_forever(self, on_gpu: Callable[[], int]) -> None:
        """Looks every SAMPLE_S, for as long as StationPlay runs."""
        while True:
            try:
                await asyncio.to_thread(self.sample, on_gpu())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Reading the server's health failed")
            await asyncio.sleep(SAMPLE_S)

    def as_dict(self) -> dict[str, Any]:
        """The latest look, and the history of each value (oldest first)."""
        latest = self.history[-1] if self.history else Sample(int(time.time() * 1000))
        kept = list(self.history)
        return {
            "every": SAMPLE_S,
            "atMs": latest.at_ms,
            "processor": {
                "own": latest.own_cpu,
                "machine": latest.cpu,
                "processors": self.processors or None,
            },
            "memory": {
                "own": latest.own_memory,
                "used": latest.memory_used,
                "total": latest.memory_total,
                "limit": latest.memory_limit,
            },
            "network": {"sending": latest.sending, "receiving": latest.receiving},
            "storage": {"free": latest.free, "total": latest.disk},
            "history": {
                "atMs": [s.at_ms for s in kept],
                "processor": [s.own_cpu for s in kept],
                "memory": [s.own_memory for s in kept],
                "sending": [s.sending for s in kept],
                "receiving": [s.receiving for s in kept],
                "gpu": [s.on_gpu for s in kept],
                "storage": [s.free for s in kept],
            },
        }

    # Files ----------------------------------------------------------------

    def _read(self, name: str) -> str | None:
        try:
            return (self.proc / name).read_text()
        except (OSError, UnicodeDecodeError):
            return None

    def _cgroup_files(self, controller: str) -> list[Path]:
        """Where this process's cgroup's files may be, most likely first:
        at its path under the cgroup files (cgroup v2, or v1's
        `controller`), or at their top (inside a container, which sees its
        own cgroup there). Worked out once."""
        if controller in self._folders:
            return self._folders[controller]
        listed = self._read("self/cgroup") or ""
        out: list[Path] = []
        for line in listed.splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            _, controllers, path = parts
            inside = path.strip().lstrip("/")
            if not controllers:  # cgroup v2
                out += [self.cgroup / inside, self.cgroup]
            elif controller in controllers.split(","):
                top = self.cgroup / controllers
                out += [top / inside, top, self.cgroup / controller / inside]
        found = self._folders[controller] = [p for p in dict.fromkeys(out) if p.is_dir()]
        return found

    def _cgroup_text(self, controller: str, name: str) -> str | None:
        """One of this process's cgroup's files (cgroup v2's, or v1's
        `controller`'s), if it's there."""
        for folder in self._cgroup_files(controller):
            with contextlib.suppress(OSError, UnicodeDecodeError):
                return (folder / name).read_text()
        return None

    def _own_cpu_s(self) -> float | None:
        """StationPlay's processor time so far, in seconds."""
        usec = _field(self._cgroup_text("cpuacct", "cpu.stat") or "", "usage_usec")  # (v2)
        if usec is not None:
            return usec / 1e6
        nsec = (self._cgroup_text("cpuacct", "cpuacct.usage") or "").strip()  # (v1)
        if nsec.isdigit():
            return int(nsec) / 1e9
        stat = self._read("self/stat")
        if stat is None:
            return None
        # (After the process's name, which may hold spaces: utime, stime and
        # the same for its children that have finished, in ticks.)
        fields = stat.rpartition(")")[2].split()
        try:
            ticks = sum(int(fields[i]) for i in (11, 12, 13, 14))
        except (IndexError, ValueError):
            return None
        return ticks / (os.sysconf("SC_CLK_TCK") or 100)

    def _own_memory(self) -> int | None:
        """StationPlay's memory, in bytes."""
        stat = self._cgroup_text("memory", "memory.stat") or ""
        current = (self._cgroup_text("memory", "memory.current") or "").strip()  # (v2)
        if current.isdigit():
            return max(0, int(current) - (_field(stat, "inactive_file") or 0))
        usage = (self._cgroup_text("memory", "memory.usage_in_bytes") or "").strip()  # (v1)
        if usage.isdigit():
            return max(0, int(usage) - (_field(stat, "total_inactive_file") or 0))
        rss = _field(self._read("self/status") or "", "VmRSS:")
        return rss * 1024 if rss is not None else None

    def _memory(self, own: int | None) -> tuple[int | None, int | None, bool]:
        """(Used, total, whether that's the container's limit): the
        container's limit, if it has one; otherwise the machine's."""
        info = self._read("meminfo") or ""
        total = _field(info, "MemTotal:")
        available = _field(info, "MemAvailable:")
        machine = total * 1024 if total is not None else None
        limit = (
            self._cgroup_text("memory", "memory.max")
            or self._cgroup_text("memory", "memory.limit_in_bytes")
            or ""
        ).strip()
        if limit.isdigit() and own is not None:
            most = int(limit)
            if most < NO_LIMIT and (machine is None or most < machine):
                return own, most, True
        if total is None or available is None:
            return None, machine, False
        return (total - available) * 1024, machine, False


def _field(text: str, name: str) -> int | None:
    """The number after `name` on its line ("usage_usec 123", "MemTotal:
    16 kB")."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == name:
            with contextlib.suppress(ValueError):
                return int(parts[1])
    return None


def _processor(stat: str) -> tuple[int | None, int | None, int]:
    """From /proc/stat: the machine's busy and total processor time (all
    processors together, in ticks), and how many processors it has."""
    busy = total = None
    processors = 0
    for line in stat.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "cpu":
            try:
                ticks = [int(x) for x in parts[1:9]]
            except ValueError:
                continue
            total = sum(ticks)
            busy = total - ticks[3] - (ticks[4] if len(ticks) > 4 else 0)  # (less idle and iowait)
        elif parts[0].startswith("cpu") and parts[0][3:].isdigit():
            processors += 1
    return busy, total, processors


def _network(dev: str) -> tuple[int | None, int | None]:
    """From /proc/net/dev: bytes received and sent, every interface but the
    loopback together."""
    received = sent = 0
    found = False
    for line in dev.splitlines():
        name, colon, rest = line.partition(":")
        fields = rest.split()
        if not colon or name.strip() == "lo" or len(fields) < 9:
            continue
        with contextlib.suppress(ValueError):
            received += int(fields[0])
            sent += int(fields[8])
            found = True
    return (received, sent) if found else (None, None)


def _share(
    busy: int | None, was_busy: int | None, total: int | None, was: int | None
) -> float | None:
    if None in (busy, was_busy, total, was):
        return None
    assert busy is not None and was_busy is not None and total is not None and was is not None
    if total <= was:
        return None
    return round(max(0.0, min(100.0, (busy - was_busy) / (total - was) * 100)), 1)


def _rate(now: int | None, before: int | None, seconds: float) -> float | None:
    """Mbps, from two byte counts `seconds` apart."""
    if now is None or before is None or now < before:
        return None
    return round((now - before) * 8 / seconds / 1e6, 2)
