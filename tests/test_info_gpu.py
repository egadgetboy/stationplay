"""INFO and the GPU (1.37.1, the owner's handoff, finding 4). Three programs
in a row that failed on the GPU and played on the CPU turn the GPU off for
every station until a restart (gpu.GPU_STRIKES_LIMIT). INFO's 2-minute
programs could do that in about 6 minutes, if its drawn panels ever failed
on a GPU. A program tapiOca makes itself never counts a strike, and once it
has failed on the GPU, it stays on the CPU for the rest of that viewing."""

from __future__ import annotations

import pytest

from app import infostation
from app.config import Settings
from app.ffmpeg import Encoder
from app.gpu import GPU_STRIKES_LIMIT, GpuManager

from .test_info_station import make

VAAPI = Encoder("vaapi", "/dev/dri/renderD128")

pytestmark = pytest.mark.info_station


def test_info_never_turns_the_gpu_off_and_stays_on_the_cpu(tmp_path):
    with make(tmp_path) as client:
        ctx = client.app.state.ctx
        info = infostation.find(ctx.db.list_channels())
        assert info is not None
        b = ctx.broadcaster(info.id)
        gpu = GpuManager(Settings(), active=VAAPI, state="gpu")
        for _ in range(GPU_STRIKES_LIMIT + 1):
            b._cpu_only.add(infostation.KEY)  # (failed on the GPU: see _play_item)
            b._rescued_on_cpu(infostation.KEY, gpu)
            assert infostation.KEY in b._cpu_only
        assert (gpu.state, gpu.strikes) == ("gpu", 0)


def test_a_regular_programs_strikes_count_as_before(tmp_path):
    with make(tmp_path) as client:
        ctx = client.app.state.ctx
        info = infostation.find(ctx.db.list_channels())
        b = ctx.broadcaster(info.id)
        gpu = GpuManager(Settings(), active=VAAPI, state="gpu")
        for n in range(GPU_STRIKES_LIMIT):
            b._cpu_only.add(f"20{n}")
            b._rescued_on_cpu(f"20{n}", gpu)
            assert f"20{n}" not in b._cpu_only  # (the GPU again next time)
        assert gpu.state == "disabled"
