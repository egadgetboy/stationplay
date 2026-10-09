"""The server's health on the Stats tab (health.py): read from Linux's own
files, here made up in a folder of their own, as a Docker container (cgroup
v2 or v1) and a machine without them have them."""

from __future__ import annotations

import os
from pathlib import Path

from app.health import HISTORY_S, SAMPLE_S, Health

NET = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: {lo} 10 0 0 0 0 0 0 {lo} 10 0 0 0 0 0 0
  eth0: {rx} 900 0 0 0 0 0 0 {tx} 800 0 0 0 0 0 0
"""


class Clock:
    def __init__(self) -> None:
        self.at = 1000.0

    def __call__(self) -> float:
        return self.at


def write(folder: Path, name: str, text: str) -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def machine(proc: Path, busy: int, idle: int, rx: int, tx: int) -> None:
    """A machine with two processors, 16 GB of memory (half of it free)."""
    write(proc, "stat", f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 0 0 1\ncpu1 1 0 0 1\nintr 5\n")
    write(proc, "meminfo", "MemTotal:       16000000 kB\nMemAvailable:    8000000 kB\n")
    write(proc, "net/dev", NET.format(lo=999_999, rx=rx, tx=tx))


def test_a_container_on_cgroup_v2(tmp_path):
    proc, cgroup, clock = tmp_path / "proc", tmp_path / "cgroup", Clock()
    write(proc, "self/cgroup", "0::/\n")
    write(cgroup, "memory.current", "524288000\n")
    write(cgroup, "memory.stat", "anon 400000000\ninactive_file 104857600\nactive_file 5\n")
    write(cgroup, "memory.max", "2147483648\n")
    machine(proc, busy=200, idle=800, rx=1_000_000, tx=2_000_000)
    write(cgroup, "cpu.stat", "usage_usec 3000000\nuser_usec 2000000\n")
    health = Health(tmp_path, proc, cgroup, clock)
    first = health.sample(on_gpu=1)
    # The first look has nothing to work out rates from.
    assert (first.cpu, first.own_cpu, first.sending, first.receiving) == (None, None, None, None)
    clock.at += 5
    machine(proc, busy=400, idle=1400, rx=1_625_000, tx=3_250_000)
    write(cgroup, "cpu.stat", "usage_usec 4000000\n")
    got = health.sample(on_gpu=2)
    assert got.cpu == 25.0  # (200 of 800 ticks busy)
    assert got.own_cpu == 10.0  # (1 second of 5, on 2 processors)
    assert (got.receiving, got.sending) == (1.0, 2.0)  # Mbps, the loopback left out
    # Its memory, less what the kernel can drop; of its limit, which is less than the machine's.
    assert got.own_memory == 524288000 - 104857600
    assert (got.memory_used, got.memory_total, got.memory_limit) == (got.own_memory, 2**31, True)
    assert got.free is not None and got.disk is not None and got.free <= got.disk
    shown = health.as_dict()
    assert shown["processor"] == {"own": 10.0, "machine": 25.0, "processors": 2}
    assert shown["memory"]["limit"] and shown["network"] == {"sending": 2.0, "receiving": 1.0}
    assert shown["history"]["processor"] == [None, 10.0]
    assert shown["history"]["gpu"] == [1, 2]
    # The last 10 minutes, and no more.
    for _ in range(200):
        clock.at += SAMPLE_S
        health.sample()
    assert len(health.as_dict()["history"]["memory"]) == HISTORY_S / SAMPLE_S


def test_a_container_on_cgroup_v1_without_a_memory_limit(tmp_path):
    proc, cgroup, clock = tmp_path / "proc", tmp_path / "cgroup", Clock()
    # (Inside a container, its own cgroup is at the top, whatever path it's given.)
    write(
        proc, "self/cgroup", "4:memory:/docker/abc\n2:cpu,cpuacct:/docker/abc\n1:name=systemd:/\n"
    )
    write(cgroup, "cpu,cpuacct/cpuacct.usage", "2000000000\n")
    write(cgroup, "cpu,cpuacct/cpu.stat", "nr_periods 0\nnr_throttled 0\n")  # (v1's: no usage)
    write(cgroup, "memory/memory.usage_in_bytes", "300000000\n")
    write(cgroup, "memory/memory.stat", "cache 5\ntotal_inactive_file 100000000\n")
    write(cgroup, "memory/memory.limit_in_bytes", "9223372036854771712\n")  # (no limit)
    machine(proc, busy=100, idle=100, rx=0, tx=0)
    health = Health(tmp_path, proc, cgroup, clock)
    health.sample()
    clock.at += 10
    write(cgroup, "cpu,cpuacct/cpuacct.usage", "7000000000\n")
    got = health.sample()
    assert got.own_cpu == 25.0  # (5 seconds of 10, on 2 processors)
    assert got.own_memory == 200_000_000
    # No limit: the machine's memory, as it says what's available.
    assert (got.memory_used, got.memory_total, got.memory_limit) == (
        8_000_000 * 1024,
        16_000_000 * 1024,
        False,
    )


def test_what_isnt_there_is_not_available(tmp_path):
    proc, clock = tmp_path / "nothing", Clock()
    proc.mkdir()
    health = Health(tmp_path / "gone", proc, tmp_path / "no-cgroup", clock)
    health.sample()
    clock.at += 5
    got = health.sample()
    for value in (got.cpu, got.own_cpu, got.own_memory, got.memory_used, got.memory_total):
        assert value is None
    assert (got.sending, got.receiving, got.free, got.disk) == (None, None, None, None)
    shown = health.as_dict()
    assert shown["processor"] == {"own": None, "machine": None, "processors": None}
    assert shown["memory"] == {"own": None, "used": None, "total": None, "limit": False}
    assert shown["storage"] == {"free": None, "total": None}


def test_without_a_cgroup_its_own_process_counts(tmp_path):
    """(Not in a container: StationPlay's own use is this process's.)"""
    proc, clock = tmp_path / "proc", Clock()
    machine(proc, busy=0, idle=10, rx=5, tx=5)
    write(proc, "self/status", "Name:\tpython\nVmRSS:\t  51200 kB\n")
    # utime, stime, cutime and cstime are the 14th to 17th fields, after the name.
    write(proc, "self/stat", "42 (python main) S " + " ".join(["0"] * 10) + " 100 50 0 0 20 0\n")
    health = Health(tmp_path, proc, tmp_path / "no-cgroup", clock)
    health.sample()
    assert health.history[-1].own_memory == 51200 * 1024
    clock.at += 10
    write(proc, "self/stat", "42 (python main) S " + " ".join(["0"] * 10) + " 300 50 0 0 20 0\n")
    got = health.sample()
    # 200 ticks (2 seconds, at 100 a second), of 10 seconds on 2 processors.
    ticks = os.sysconf("SC_CLK_TCK")
    assert got.own_cpu is not None and abs(got.own_cpu - 200 / ticks / 20 * 100) < 0.01
