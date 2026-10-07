"""Makes the Station ID card's jingles: fifteen short, gentle station idents.

Each one is a little tune that's over within two seconds (so a 3-second
card hears all of it), a soft chord that holds under the card, a quieter
echo of the tune for a 10-second card, and a fade to silence. The card
plays as much of it as it's long and fades it out at the end. They sit
under the card, quieter than programs, to say "you're watching this
station" rather than to get attention: each is evened out so its loudest
three seconds (all a 3-second card hears) are 3 dB under the loudness
programs are brought to, with its peaks well under theirs.

Everything is synthesized here from scratch with the instruments in
sound.py: no recordings, nothing borrowed from any real station.

Writes app/assets/ident/jingle-<n>.m4a.

    python3 tools/bumper/jingles.py      (needs numpy and ffmpeg)
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np
import sound
from sound import (
    SR,
    band,
    bell,
    brass,
    flute,
    mallet,
    organ,
    piano,
    place,
    pluck,
    square,
    strings,
    times,
)  # fmt: skip

OUT = Path(__file__).resolve().parents[2] / "app" / "assets" / "ident"
LENGTH_S = 10.0
# Programs are evened out to -24 LUFS with peaks under -2 dBTP. A jingle's
# loudest three seconds are 3 dB under that, and its peaks lower still.
LOUDEST_3S_LUFS = -27.0
PEAK_DBTP = -6.0


def room(x: np.ndarray, wet: float = 0.22, decay_s: float = 1.1) -> np.ndarray:
    """A soft room around it: the sound convolved with decaying noise."""
    n = int(decay_s * SR)
    ir = sound.rng.standard_normal(n) * np.exp(-times(n) / (decay_s / 5))
    ir = band(ir, 200, 6000)
    ir /= np.sqrt(np.sum(ir**2)) + 1e-9
    size = len(x) + n
    wet_sig = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    return (1 - wet) * x + wet * wet_sig * 0.6


def pad(notes: list[float], start: float, end: float, level: float) -> tuple[np.ndarray, float]:
    """A soft held chord from `start` that fades out by `end`."""
    sig = band(strings(notes, end - start, attack=0.6), 0, 3200)
    tt = times(len(sig))
    span = end - start
    sig *= np.clip((span - tt) / (span * 0.45), 0, 1)
    return sig * level, start


def chime(mix: np.ndarray) -> None:
    """Bells rising through a C chord over strings."""
    for at, note in ((0.0, 72), (0.16, 76), (0.32, 79), (0.56, 84)):
        place(mix, bell(note, 2.4, 1.0), at, 0.30)
    place(mix, *pad([60, 64, 67, 72], 0.45, 8.0, 0.42))
    for at, note in ((5.8, 79), (6.0, 84)):
        place(mix, bell(note, 2.0, 0.9), at, 0.12)


def marimba(mix: np.ndarray) -> None:
    """A marimba figure landing on an F chord on the piano."""
    for at, note in ((0.0, 65), (0.13, 69), (0.26, 72), (0.39, 77), (0.7, 76), (0.84, 77)):
        place(mix, mallet(note, 1.0, 0.35), at, 0.34)
    for note in (53, 57, 60, 65):
        place(mix, piano(note, 3.5), 1.0, 0.16)
    place(mix, *pad([53, 60, 65, 69], 1.0, 8.0, 0.32))
    for at, note in ((5.8, 72), (5.93, 77)):
        place(mix, mallet(note, 1.0, 0.35), at, 0.14)


def glow(mix: np.ndarray) -> None:
    """A soft brass chord swelling under bells, in D."""
    swell = np.zeros(int(2.6 * SR))
    for note in (50, 57, 62, 66):
        swell += brass(note, 2.6, 0.45)
    tt = times(len(swell))
    swell *= np.clip(tt / 0.5, 0, 1) * np.clip((2.6 - tt) / 1.2, 0, 1)
    place(mix, band(swell, 0, 2500), 0.0, 0.07)
    for at, note in ((0.35, 74), (0.55, 78), (0.75, 81), (1.05, 86)):
        place(mix, bell(note, 2.2, 0.9), at, 0.24)
    place(mix, *pad([50, 57, 62, 66], 1.6, 8.0, 0.34))
    place(mix, bell(81, 2.0, 0.9), 5.9, 0.11)


def breeze(mix: np.ndarray) -> None:
    """A flute tune over a plucked bass, with a sparkle, in G."""
    for at, note, held in ((0.0, 67, 0.3), (0.22, 71, 0.3), (0.44, 74, 0.3), (0.66, 79, 0.9)):
        place(mix, flute(note, held), at, 0.22)
    place(mix, pluck(43, 1.6, 0.3), 0.0, 0.30)
    place(mix, pluck(50, 1.6, 0.3), 0.66, 0.26)
    for at, note in ((1.15, 86), (1.3, 91)):
        place(mix, bell(note, 1.2, 0.5), at, 0.10)
    place(mix, *pad([55, 62, 67, 71], 0.9, 8.0, 0.32))
    for at, note in ((5.8, 74), (6.02, 79)):
        place(mix, flute(note, 0.4), at, 0.10)


def sunrise(mix: np.ndarray) -> None:
    """A piano rising through an E-flat chord, then strings."""
    for at, note in ((0.0, 63), (0.14, 67), (0.28, 70), (0.42, 75), (0.62, 79)):
        place(mix, piano(note, 2.6), at, 0.20)
    place(mix, *pad([51, 58, 63, 67], 0.7, 8.0, 0.34))
    for at, note in ((5.8, 75), (6.0, 79)):
        place(mix, piano(note, 2.0), at, 0.09)


def music_box(mix: np.ndarray) -> None:
    """A music box's little turn in A, over a soft chord."""
    for at, note in ((0.0, 81), (0.15, 85), (0.3, 88), (0.45, 86), (0.6, 85), (0.85, 81)):
        place(mix, bell(note, 1.6, 0.45), at, 0.22)
    place(mix, *pad([57, 61, 64, 69], 0.9, 8.0, 0.30))
    for at, note in ((5.8, 85), (5.95, 88)):
        place(mix, bell(note, 1.2, 0.4), at, 0.10)


def nightcap(mix: np.ndarray) -> None:
    """A warm major seventh on the piano in A-flat, late-night and easy."""
    for at, note in ((0.0, 56), (0.12, 63), (0.24, 68), (0.36, 72), (0.48, 75), (0.6, 79)):
        place(mix, piano(note, 3.0), at, 0.16)
    place(mix, *pad([56, 63, 67, 72], 0.8, 8.0, 0.30))
    place(mix, piano(84, 2.0), 5.9, 0.07)


def herald(mix: np.ndarray) -> None:
    """A soft brass call in B-flat, answered by bells."""
    for at, note, held in ((0.0, 58, 0.25), (0.28, 65, 0.25), (0.56, 70, 1.4)):
        place(mix, band(brass(note, held + 0.3, 0.55), 0, 3000), at, 0.10)
    for at, note in ((0.9, 82), (1.05, 86), (1.2, 89)):
        place(mix, bell(note, 2.0, 0.9), at, 0.16)
    place(mix, *pad([46, 53, 58, 62], 1.2, 8.0, 0.30))
    place(mix, bell(82, 1.8, 0.8), 5.9, 0.08)


def harp(mix: np.ndarray) -> None:
    """A harp sweeping up a D scale to a held chord."""
    scale = (62, 64, 66, 67, 69, 71, 73, 74, 76, 78, 79, 81, 83, 86)
    for n, note in enumerate(scale):
        place(mix, band(pluck(note, 2.2, 0.3, 0.9985), 0, 5000), n * 0.05, 0.18)
    for note in (62, 66, 69, 74):
        place(mix, pluck(note, 3.0, 0.4, 0.9992), 0.85, 0.12)
    place(mix, *pad([50, 57, 62, 66], 0.9, 8.0, 0.30))
    for n, note in enumerate((74, 78, 81, 86)):
        place(mix, pluck(note, 1.6, 0.4, 0.998), 5.8 + n * 0.06, 0.07)


def vibes(mix: np.ndarray) -> None:
    """A vibraphone line in G, a little jazzy."""
    for at, note in ((0.0, 67), (0.16, 71), (0.32, 74), (0.5, 78), (0.72, 76), (0.9, 79)):
        place(mix, _vibraphone(note), at, 0.22)
    place(mix, *pad([55, 59, 62, 66], 1.0, 8.0, 0.28))
    place(mix, _vibraphone(83), 5.9, 0.09)


def _vibraphone(note: float) -> np.ndarray:
    """A mallet note with the slow pulse of a vibraphone's fan."""
    sig = mallet(note, 1.6, 0.9)
    return sig * (1 + 0.25 * np.sin(2 * np.pi * 5.5 * times(len(sig))))


def pastoral(mix: np.ndarray) -> None:
    """A flute tune over strings in F, unhurried."""
    tune = ((0.0, 72, 0.3), (0.3, 74, 0.3), (0.6, 77, 0.45), (1.05, 76, 0.25), (1.3, 77, 0.9))
    for at, note, held in tune:
        place(mix, flute(note, held), at, 0.20)
    place(mix, *pad([53, 60, 65, 69], 0.4, 8.0, 0.32))
    place(mix, flute(81, 0.6), 5.8, 0.08)


def sparkle(mix: np.ndarray) -> None:
    """Bells tumbling down and settling on a bright chord in C."""
    for at, note in ((0.0, 96), (0.1, 93), (0.2, 91), (0.3, 88), (0.4, 84)):
        place(mix, bell(note, 1.4, 0.6), at, 0.14)
    for note in (79, 84, 88):
        place(mix, bell(note, 2.4, 1.0), 0.65, 0.12)
    place(mix, *pad([48, 55, 60, 64], 0.7, 8.0, 0.32))
    for at, note in ((5.8, 91), (5.9, 88)):
        place(mix, bell(note, 1.2, 0.5), at, 0.07)


def console(mix: np.ndarray) -> None:
    """An organ chord and a gentle lead in E-flat, like a 1960s station."""
    chord = sum(organ(note, 2.4, 0.004) for note in (51, 58, 63, 67))
    tt = times(len(chord))
    chord *= np.clip(tt / 0.3, 0, 1) * np.clip((2.4 - tt) / 1.0, 0, 1)
    place(mix, band(chord, 0, 2500), 0.0, 0.05)
    for at, note, held in ((0.15, 70, 0.22), (0.4, 75, 0.22), (0.65, 79, 0.7)):
        place(mix, band(square(note, held, 0.35), 0, 2200), at, 0.05)
    place(mix, *pad([51, 58, 63, 67], 1.6, 8.0, 0.30))
    place(mix, band(square(82, 0.4, 0.3), 0, 2200), 5.9, 0.03)


def swell(mix: np.ndarray) -> None:
    """Strings rising from low to high in E, with a bell at the top."""
    rise = band(strings([40, 47, 52, 56, 59, 64], 2.2, attack=1.0), 0, 3500)
    place(mix, rise, 0.0, 0.40)
    place(mix, bell(88, 2.4, 1.0), 1.0, 0.18)
    place(mix, bell(83, 2.4, 1.0), 1.15, 0.12)
    place(mix, *pad([52, 59, 64, 68], 1.6, 8.0, 0.30))
    place(mix, bell(88, 1.8, 0.8), 5.9, 0.07)


def bounce(mix: np.ndarray) -> None:
    """A playful marimba and plucked bass in B-flat."""
    for at, note in ((0.0, 70), (0.12, 74), (0.24, 77), (0.48, 74), (0.6, 82)):
        place(mix, mallet(note, 1.0, 0.3), at, 0.30)
    for at, note in ((0.0, 46), (0.48, 53), (0.6, 58)):
        place(mix, pluck(note, 1.4, 0.3), at, 0.26)
    place(mix, *pad([46, 53, 58, 62], 0.9, 8.0, 0.28))
    for at, note in ((5.8, 77), (5.92, 82)):
        place(mix, mallet(note, 1.0, 0.3), at, 0.12)


JINGLES: tuple[Callable[[np.ndarray], None], ...] = (
    chime, marimba, glow, breeze, sunrise, music_box, nightcap, herald,
    harp, vibes, pastoral, sparkle, console, swell, bounce,
)  # fmt: skip


def render(make: Callable[[np.ndarray], None], seed: int) -> np.ndarray:
    sound.rng = np.random.default_rng(seed)
    mix = np.zeros(int(LENGTH_S * SR))
    make(mix)
    mix = room(mix)
    tt = times(len(mix))
    mix *= np.clip((LENGTH_S - 0.3 - tt) / 1.5, 0, 1)  # silent by the end
    return mix / max(1.0, np.abs(mix).max() / 0.95)


def loudness(path: Path) -> tuple[float, float]:
    """(Its loudest three seconds in LUFS, its true peak in dBTP.)"""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr  # fmt: skip
    short = [float(x) for x in re.findall(r"\bS:\s*(-?[\d.]+)", out)]
    peak = float(re.findall(r"Peak:\s*(-?[\d.]+)", out)[-1])
    return max(short), peak


def write(path: Path, mix: np.ndarray) -> tuple[float, float]:
    """To AAC, evened out so its loudest three seconds are LOUDEST_3S_LUFS
    and its peaks no higher than PEAK_DBTP. Returns (that loudness, peak)."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "x.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((mix * 32767).astype("<i2").tobytes())
        loudest, peak = loudness(wav)
        gain = min(LOUDEST_3S_LUFS - loudest, PEAK_DBTP - peak)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(wav), "-af", f"volume={gain:.2f}dB",
             "-c:a", "aac", "-b:a", "96k", "-ar", "48000", str(path)],
            check=True,
        )  # fmt: skip
    return loudness(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for n, make in enumerate(JINGLES, 1):
        path = OUT / f"jingle-{n}.m4a"
        loudest, peak = write(path, render(make, seed=7000 + n))
        print(
            f"{path.name:13} {make.__name__:10} loudest 3s {loudest:6.1f} LUFS, peak {peak:5.1f} dBTP"
        )


if __name__ == "__main__":
    main()
