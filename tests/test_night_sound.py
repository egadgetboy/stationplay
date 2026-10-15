"""Night mode's sound, as tapiOca makes it (hls.NIGHT_SOUND) for apps
that can't make it themselves (Apple's, Roku's), and for converted copies:
it only ever turns sound down, loud scenes the most, and cuts rumble under
50 Hz (1.36.4), so turning night mode on never makes anything louder (the owner's report: in 1.31 and before, it
turned everything up 8 dB after turning loud sounds down, so most programs
got louder). The Android app makes the same sound on the device (its
NightMode, with the same curve: these levels are its too)."""

from __future__ import annotations

import os
import re
import subprocess

import pytest

from app import hls

FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")
SECONDS = 4
# Speech-like sound: a 220 Hz voice in syllables, four a second (the
# Android app's tests use the same), and loud, dense sound (an action
# scene's).
VOICE = "abs(sin(PI*4*t))^3*(sin(2*PI*220*t)+0.5*sin(2*PI*440*t))"


def measured(source: str, night: bool) -> float:
    """The mean level (dB, RMS) of `source` (a lavfi source), over its
    second half (once night mode has settled), with or without night
    mode's sound."""
    chain = f"{hls.NIGHT_SOUND}," if night else ""
    done = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostdin", "-f", "lavfi", "-i", source, "-t", str(SECONDS),
         "-af", f"{chain}atrim=start={SECONDS / 2},volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    found = re.search(r"mean_volume: (-?[\d.]+) dB", done.stderr)
    assert found, done.stderr[-500:]
    return float(found.group(1))


def tone(db: float) -> str:
    """A 1 kHz tone peaking at `db`, on two channels."""
    return f"aevalsrc={10 ** (db / 20):.6f}*sin(2*PI*1000*t)|{10 ** (db / 20):.6f}*sin(2*PI*1000*t):s=48000"  # fmt: skip


def voice(db: float) -> str:
    """The speech-like sound at `db` RMS (its peaks about 9 dB above), on two
    channels."""
    k = 10 ** (db / 20) / 0.442  # (the voice's own RMS, at 1)
    return f"aevalsrc={k:.6f}*{VOICE}|{k:.6f}*{VOICE}:s=48000"


def action(db: float) -> str:
    """Loud, dense sound at about `db` RMS (-15 at most), on two channels."""
    assert db <= -15
    amplitude = 10 ** ((db + 14.3) / 20)  # (pink noise's RMS is 14.3 dB under its amplitude)
    return f"anoisesrc=color=pink:amplitude={amplitude:.6f}:sample_rate=48000:seed=7,pan=stereo|c0=c0|c1=c0"  # fmt: skip


@pytest.fixture(scope="module", autouse=True)
def _ffmpeg():
    if subprocess.run([FFMPEG, "-version"], capture_output=True).returncode != 0:
        pytest.skip("FFmpeg isn't installed")


@pytest.mark.parametrize(
    "source",
    [tone(-40), tone(-30), tone(-20), tone(-6), voice(-36), voice(-30), voice(-24), voice(-20),
     action(-24), action(-15)],
    ids=["tone-40", "tone-30", "tone-20", "tone-6", "voice-36", "voice-30", "voice-24", "voice-20",
         "action-24", "action-15"],
)  # fmt: skip
def test_nothing_gets_louder(source):
    before, after = measured(source, False), measured(source, True)
    assert after <= before + 0.3, (before, after)


def test_quiet_sound_is_left_as_it_is():
    before, after = measured(tone(-40), False), measured(tone(-40), True)
    assert abs(after - before) <= 0.5, (before, after)


def test_voices_stay_close_to_where_they_were():
    # Dialogue as quiet films mix it (-30 dB RMS): at most 3 dB down.
    before, after = measured(voice(-30), False), measured(voice(-30), True)
    assert before - 3 <= after <= before + 0.3, (before, after)


def test_loud_sound_comes_down_the_most():
    before, after = measured(tone(-6), False), measured(tone(-6), True)
    assert after <= before - 12, (before, after)
    before, after = measured(action(-15), False), measured(action(-15), True)
    assert after <= before - 10, (before, after)


def test_voices_and_action_end_up_a_few_decibels_apart():
    # 18 dB apart in the film; 6 or less with night mode on.
    assert abs(measured(action(-15), False) - measured(voice(-33), False) - 18) <= 1
    voices, loud = measured(voice(-33), True), measured(action(-15), True)
    assert loud - voices <= 6, (voices, loud)


@pytest.mark.parametrize(
    ("peak", "turned"),
    # (The curve: nothing below -29 dB; 1 dB down for each 3 louder up to -22,
    # then 19 down for each 20 louder. Android's NightMode.gainDb is the same.)
    [(-40, 0.0), (-25, -4 / 3), (-10, -7 / 3 - 12 * 0.95), (-3, -7 / 3 - 19 * 0.95)],
)
def test_the_curve_is_the_android_apps(peak, turned):
    before, after = measured(tone(peak), False), measured(tone(peak), True)
    assert after - before == pytest.approx(turned, abs=1.5), (before, after)


def pitch(hz: float, db: float) -> str:
    """A tone of `hz` peaking at `db`, on two channels."""
    a = 10 ** (db / 20)
    return f"aevalsrc={a:.6f}*sin(2*PI*{hz}*t)|{a:.6f}*sin(2*PI*{hz}*t):s=48000"


# The owner, October 14 (1.36.4): "cut audio 0-50 Hz". A steep cut from 50 Hz down (24 dB
# an octave, 6 dB down at 50 Hz), so rumble no longer shakes the room, nor pulls the
# voices down with it. A bass voice (100 Hz and up) stays as it was.
@pytest.mark.parametrize(("hz", "down"), [(20, 30), (30, 17), (40, 9)])
def test_rumble_under_50_hz_is_cut(hz, down):
    before, after = measured(pitch(hz, -40), False), measured(pitch(hz, -40), True)
    assert after <= before - down, (hz, before, after)


@pytest.mark.parametrize("hz", [100, 200])
def test_bass_from_100_hz_stays(hz):
    before, after = measured(pitch(hz, -40), False), measured(pitch(hz, -40), True)
    assert abs(after - before) <= 0.8, (hz, before, after)


def voice_band(source: str, night: bool) -> float:
    """As measured, but only above 150 Hz, where the voice is (the rumble
    left out of the measuring, not out of what night mode heard)."""
    chain = f"{hls.NIGHT_SOUND}," if night else ""
    band = "highpass=f=150:poles=2,highpass=f=150:poles=2,"
    done = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostdin", "-f", "lavfi", "-i", source, "-t", str(SECONDS),
         "-af", f"{chain}{band}atrim=start={SECONDS / 2},volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip
    found = re.search(r"mean_volume: (-?[\d.]+) dB", done.stderr)
    assert found, done.stderr[-500:]
    return float(found.group(1))


def test_rumble_no_longer_pulls_the_voices_down():
    # (1.36.4's audit: the voice at -30 dB RMS under loud rumble, 30 Hz at -6 dB. Before
    # the cut, night mode turned everything down for the rumble, the voice 15 dB with it.)
    k, a = 10 ** (-30 / 20) / 0.442, 10 ** (-6 / 20)
    both = f"{k:.6f}*{VOICE}+{a:.6f}*sin(2*PI*30*t)"
    alone = voice_band(voice(-30), True)
    under = voice_band(f"aevalsrc={both}|{both}:s=48000", True)
    assert under >= alone - 3, (alone, under)
