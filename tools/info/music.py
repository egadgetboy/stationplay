"""The INFO station's music (1.34.1, the owner): a light, easy tune under
the pearls, 30 seconds that loop without a seam, made here from scratch
(the bumper's own instruments: nothing recorded, nothing borrowed).

At 80 beats a minute, a beat is 0.75 seconds: a pearl leaves the ring
every half beat (render.py's LEAVES), and each one that passes through it
rings a soft bell, from the chord of the moment, on the side of the screen it
flies out to. Under them: a soft string pad, a round bass, and a quiet
tick on the off-beats. Evened out to -24 LUFS, the loudness tapiOca brings
programs to, so it plays as loud as anything else at the same volume, with
nothing sharp in it.

    python tools/info/music.py /tmp/info.wav        (render.py makes it itself)
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

# (The bumper's instruments.)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bumper"))
import sound
from sound import SR, band, bell, hat, mallet, strings

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render

LOOP = render.SECONDS
BEAT = 2 * render.LEAVES  # 0.75 s: 80 beats a minute (a pearl every half beat)
TARGET_LUFS = -24.0
# Ten bars of four beats, one chord each (MIDI notes), back to the first.
D, E, FS, G, A, B = 62, 64, 66, 67, 69, 71
CHORDS = [
    (D, FS + 12, A), (B - 12, D, FS), (G - 12, B - 12, D), (A - 12, E, A - 12 + 4 + 12),
    (D, FS, A), (B - 12, D, FS), (E, G, B), (A - 12, E, A),
    (G - 12, B - 12, D), (A - 12, E, A - 12 + 16),
]  # fmt: skip


def passes() -> list[tuple[float, float]]:
    """When each pearl passes through the ring, in the loop, and which way
    it flies out (its angle)."""
    k = math.log(render.FAR) / math.log(render.FAR / render.NEAR)
    return [((p.leaves + k * render.FLIGHT) % LOOP, p.angle) for p in render.pearls()]


def add(out: np.ndarray, sig: np.ndarray, at: float, left: float, right: float) -> None:
    """`sig` into the stereo mix, at `at` seconds (wrapping round the loop's
    three copies), at these levels."""
    i = round(at * SR) % len(out)
    end = i + len(sig)
    take = min(end, len(out)) - i
    out[i : i + take, 0] += sig[:take] * left
    out[i : i + take, 1] += sig[:take] * right
    if end > len(out):
        rest = end - len(out)
        out[:rest, 0] += sig[take:] * left
        out[:rest, 1] += sig[take:] * right


def tune() -> np.ndarray:
    sound.rng = np.random.default_rng(1340)
    n = int(LOOP * SR)
    out = np.zeros((n, 2))
    # (The beat lines up with the pearls passing the ring.)
    start = passes()[0][0] % BEAT
    for bar, chord in enumerate(CHORDS):
        at = start + bar * 4 * BEAT
        pad = strings([c - 12 for c in chord], 4 * BEAT + 1.2, attack=0.9)
        pad *= np.clip((4 * BEAT + 1.2 - sound.times(len(pad))) / 1.2, 0, 1)  # (into the next)
        add(out, band(pad, 120, 2600), at, 0.16, 0.16)
        root = min(chord) - 12
        for beat in (0, 2):
            add(out, mallet(root, 1.4, decay=0.5), at + beat * BEAT, 0.34, 0.34)
        for beat in range(4):
            tick = band(hat(0.05), 6000, 12000)
            add(out, tick, at + (beat + 0.5) * BEAT, 0.035, 0.05)
    # The bells: one for each pearl as it passes, rising and falling through
    # the chord of the moment, toward the side it flies out to.
    shape = [0, 1, 2, 1, 2, 3, 2, 1]
    for n_pass, (at, angle) in enumerate(sorted(passes())):
        bar = int(((at - start) % LOOP) // (4 * BEAT))
        notes = sorted(CHORDS[bar % len(CHORDS)])
        step = shape[n_pass % len(shape)]
        note = notes[step % 3] + 12 * (1 + step // 3)
        pan = 0.5 + 0.35 * math.cos(angle)
        ring = bell(note, 2.2, decay=0.5)
        add(out, ring, at, 0.16 * math.cos(pan * math.pi / 2), 0.16 * math.sin(pan * math.pi / 2))
    return out


def write(path: Path) -> None:
    """The loop as 48 kHz stereo WAV, at TARGET_LUFS (peaks under -2 dBTP)."""
    mix = tune()
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.wav"
        with wave.open(str(raw), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            peak = np.abs(mix).max() or 1.0
            w.writeframes((mix / peak * 0.5 * 32767).astype("<i2").tobytes())
        measured = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(raw), "-af", "loudnorm=print_format=json",
             "-f", "null", "-"],
            capture_output=True, text=True, check=True,
        ).stderr  # fmt: skip
        stats = json.loads(measured[measured.rindex("{") :])
        gain = min(TARGET_LUFS - float(stats["input_i"]), -2.0 - float(stats["input_tp"]))
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(raw), "-af",
             f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", str(path)],
            check=True,
        )  # fmt: skip


if __name__ == "__main__":
    write(Path(sys.argv[1]))
