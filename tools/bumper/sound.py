"""Makes the tune-in bumper's sound: someone flipping the dial of an old TV.

The knob clicks over again and again: a moment of static, a snippet of
whatever show is on (a brass fanfare, a cartoon, a western, the news, a game
show, a lounge combo, a ballgame, a doo-wop piano, a movie's strings, a rock
band, a kids' show, disco, a space show, a waltz, a soap opera's organ, surf
guitar), each heard through a small TV's speaker, until the fine tuning
settles as the show begins. It plays under the whole bumper, to make people
look up and read the card.

Each length (3, 5, 10 and 15 seconds) has VARIANTS different versions: their
own shows, order, timing, keys, tempos and static, so it isn't the same sound
every time. Everything is synthesized here from scratch: no recordings,
nothing borrowed from any real program.

Writes app/assets/bumper/tuning-<length>-<n>.m4a, and dial.json with where
each one's knob clicks (the picture flickers with them). Also landing.m4a:
the knob clicking onto the station itself, a burst of static and the fine
tuning settling, for when the bumper's last third plays the show's own sound.

    python3 tools/bumper/sound.py      (needs numpy and ffmpeg)
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

SR = 48000
LENGTHS = (3, 5, 10, 15)
VARIANTS = 4
OUT = Path(__file__).resolve().parents[2] / "app" / "assets" / "bumper"
TARGET_LUFS = -24.0  # the same loudness StationPlay evens programs out to

rng = np.random.default_rng(0)  # replaced per version


# ----------------------------------------------------------------- helpers


def hz(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def times(n: int) -> np.ndarray:
    return np.arange(n) / SR


def band(x: np.ndarray, low: float, high: float, order: float = 1.0) -> np.ndarray:
    """Gentle high- and low-pass (no ringing), by FFT."""
    if not len(x):
        return x
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    gain = np.ones_like(f)
    if low:
        gain /= 1 + (low / np.maximum(f, 1)) ** (2 * order)
    if high:
        gain /= 1 + (f / high) ** (2 * order)
    return np.fft.irfft(spec * gain, len(x))


def env(n: int, attack: float, decay: float) -> np.ndarray:
    tt = times(n)
    return np.minimum(1, tt / max(attack, 1e-4)) * np.exp(-tt / decay)


def gate(n: int, attack: float, release: float) -> np.ndarray:
    tt = times(n)
    length = n / SR
    return np.clip(np.minimum(tt / max(attack, 1e-4), (length - tt) / max(release, 1e-4)), 0, 1)


def place(out: np.ndarray, sig: np.ndarray, at: float, level: float = 1.0) -> None:
    i = int(at * SR)
    if i >= len(out) or i + len(sig) <= 0:
        return
    if i < 0:
        sig, i = sig[-i:], 0
    end = min(len(out), i + len(sig))
    out[i:end] += level * sig[: end - i]


def osc(freq: np.ndarray | float, n: int) -> np.ndarray:
    """Running phase for a (possibly changing) frequency."""
    f = np.broadcast_to(np.asarray(freq, dtype=float), (n,))
    return 2 * np.pi * np.cumsum(f) / SR


def norm(x: np.ndarray, rms: float = 0.12) -> np.ndarray:
    r = np.sqrt(np.mean(x**2)) if len(x) else 0
    return x * (rms / r) if r > 1e-9 else x


# ------------------------------------------------------------- instruments


def brass(note: float, length: float, bright: float = 0.8) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    f = hz(note) * (1 + 0.004 * np.sin(2 * np.pi * 5.2 * tt) * np.clip((tt - 0.15) / 0.2, 0, 1))
    ph = osc(f, n)
    b = bright * (0.35 + 0.65 * np.clip(tt / 0.05, 0, 1))  # the "blat" as it opens
    out = np.zeros(n)
    for k in range(1, 16):
        if hz(note) * k > 8000:
            break
        out += np.sin(k * ph) * b ** (k - 1) / k
    return out * gate(n, 0.02, 0.04)


def mallet(note: float, length: float, decay: float = 0.3) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    f = hz(note)
    s = np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 3.93 * tt) * np.exp(-tt * 18)
    return s * env(n, 0.002, decay)


def bell(note: float, length: float, decay: float = 1.2) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    f = hz(note)
    s = (
        np.sin(2 * np.pi * f * tt)
        + 0.35 * np.sin(2 * np.pi * f * 2.76 * tt) * np.exp(-tt * 3)
        + 0.12 * np.sin(2 * np.pi * f * 5.4 * tt) * np.exp(-tt * 7)
    )
    return s * env(n, 0.003, decay)


def pluck(note: float, length: float, bright: float = 0.5, damp: float = 0.996) -> np.ndarray:
    """A plucked string (Karplus-Strong), worked out a period at a time."""
    n = int(length * SR)
    period = max(2, round(SR / hz(note)))
    first = band(rng.uniform(-1, 1, period * 4), 0, 1200 + 7000 * bright)[:period]
    reps = n // period + 2
    out = np.empty(reps * period)
    cur = first.copy()
    for r in range(reps):
        out[r * period : (r + 1) * period] = cur
        cur = damp * 0.5 * (cur + np.roll(cur, -1))
    out = out[:n]
    return out / (np.abs(out).max() + 1e-9)


def piano(note: float, length: float) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    f = hz(note)
    out = np.zeros(n)
    for k in range(1, 9):
        fk = f * k * np.sqrt(1 + 0.0004 * k * k)
        if fk > 7000:
            break
        out += np.sin(2 * np.pi * fk * tt) / k**1.1 * np.exp(-tt * (1.2 + 0.9 * k))
    out += band(rng.standard_normal(n), 800, 4000) * np.exp(-tt / 0.004) * 0.3  # hammer
    return out * gate(n, 0.002, 0.05)


def organ(note: float, length: float, vibrato: float = 0.003) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    f = hz(note) * (1 + vibrato * np.sin(2 * np.pi * 6.5 * tt))
    out = np.zeros(n)
    for k, a in ((1, 1.0), (2, 0.7), (3, 0.45), (4, 0.35), (6, 0.2), (8, 0.15)):
        out += a * np.sin(osc(f * k, n))
    out *= 1 + 0.12 * np.sin(2 * np.pi * 6.5 * tt)
    return out * gate(n, 0.008, 0.03) / 2.5


def strings(notes: list[float], length: float, attack: float = 0.35) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    out = np.zeros(n)
    for note in notes:
        for det in (-0.07, 0.0, 0.08):
            f = (
                hz(note)
                * (1 + det / 100)
                * (1 + 0.005 * np.sin(2 * np.pi * (5.3 + det) * tt + note))
            )
            ph = osc(f, n) + rng.uniform(0, 6)
            for k in range(1, 10):
                if hz(note) * k > 6500:
                    break
                out += np.sin(k * ph) * 0.72 ** (k - 1) / k
    return out * np.clip(tt / attack, 0, 1) / (3 * len(notes))


def flute(note: float, length: float) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    f = hz(note) * (1 + 0.006 * np.sin(2 * np.pi * 5 * tt) * np.clip((tt - 0.1) / 0.2, 0, 1))
    ph = osc(f, n)
    s = np.sin(ph) + 0.18 * np.sin(2 * ph) + 0.05 * np.sin(3 * ph)
    s += 0.06 * band(rng.standard_normal(n), 1500, 5000)
    return s * gate(n, 0.05, 0.08)


def timpani(note: float, length: float) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    f = hz(note) * (1 + 0.08 * np.exp(-tt * 30))
    s = np.sin(osc(f, n)) + 0.4 * np.sin(osc(f * 1.5, n)) * np.exp(-tt * 6)
    thud = band(rng.standard_normal(n), 60, 900) * np.exp(-tt / 0.02) * 0.6
    return (s + thud) * env(n, 0.002, 0.45)


def kick(length: float = 0.3) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    f = 48 + 90 * np.exp(-tt * 35)
    return (
        np.sin(osc(f, n)) * env(n, 0.001, 0.12)
        + band(rng.standard_normal(n), 1000, 5000) * np.exp(-tt / 0.003) * 0.2
    )


def snare(length: float = 0.25) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    return band(rng.standard_normal(n), 1200, 6000) * env(n, 0.001, 0.09) * 0.8 + np.sin(
        2 * np.pi * 190 * tt
    ) * env(n, 0.001, 0.05)


def hat(length: float = 0.08, open_: bool = False) -> np.ndarray:
    n = int(length * SR)
    return band(rng.standard_normal(n), 6000, 0) * env(n, 0.001, 0.09 if open_ else 0.025) * 0.5


def brush(length: float = 0.25) -> np.ndarray:
    n = int(length * SR)
    return band(rng.standard_normal(n), 2500, 9000) * env(n, 0.015, 0.09) * 0.5


def slide_whistle(f0: float, f1: float, length: float) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    p = tt / length
    f = f0 * (f1 / f0) ** (p**0.8) * (1 + 0.012 * np.sin(2 * np.pi * 7 * tt))
    s = np.sin(osc(f, n)) + 0.08 * band(rng.standard_normal(n), 1500, 5000)
    return s * gate(n, 0.03, 0.05)


def boing(length: float) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    f = 190 + 120 * np.exp(-tt * 5) * np.sin(2 * np.pi * 11 * tt)
    ph = osc(f, n)
    return (np.sin(ph) + 0.5 * np.sin(2 * ph) + 0.25 * np.sin(3 * ph)) * env(n, 0.004, 0.35)


def square(note: float, length: float, bright: float = 0.6) -> np.ndarray:
    n = int(length * SR)
    ph = osc(hz(note), n)
    out = np.zeros(n)
    for k in range(1, 12, 2):
        out += np.sin(k * ph) * bright ** ((k - 1) / 2) / k
    return out * gate(n, 0.004, 0.03)


def crowd(length: float) -> np.ndarray:
    n = int(length * SR)
    tt = times(n)
    swell = 0.6 + 0.4 * np.sin(2 * np.pi * 0.7 * tt + rng.uniform(0, 6))
    murmur = band(rng.standard_normal(n), 300, 2400)
    wobble = band(rng.standard_normal(n), 0, 6)
    wobble /= np.abs(wobble).max() + 1e-9
    return murmur * swell * (1 + 0.35 * wobble)


def power_chord(root: float, length: float) -> np.ndarray:
    s = sum(pluck(root + d, length, 0.7, 0.9975) for d in (0, 7, 12))
    return band(np.tanh(3.5 * s), 90, 4500)


# --------------------------------------------------------------- the shows
# Each makes a few seconds of a show playing along; the dial lands in the
# middle of it. `key` shifts it (semitones), `pace` speeds it up or slows it.


def fanfare(n, key, pace):
    out = np.zeros(n)
    beat = 0.16 / pace
    chords = ([58, 62, 65, 70], [58, 62, 65, 70], [60, 64, 67, 72], [65, 69, 72, 77])
    for rep in range(2):
        base = rep * beat * 8
        for i, chord in enumerate(chords):
            length = beat * (0.75 if i < 3 else 4)
            for note in chord:
                place(out, brass(note + key, length), base + 0.05 + i * beat, 0.22)
        place(out, timpani(41 + key, 1.0), base + 0.05 + 3 * beat, 0.35)
    return out


def cartoon(n, key, pace):
    out = np.zeros(n)
    place(out, slide_whistle(520 * 2 ** (key / 12), 1500 * 2 ** (key / 12), 0.42 / pace), 0.0, 0.25)
    for i, note in enumerate((84, 81, 79, 76, 72, 76, 79, 84)):
        place(out, mallet(note + key, 0.4, 0.18), 0.45 / pace + i * 0.06 / pace, 0.26)
    place(out, boing(0.6), 0.95 / pace, 0.4)
    place(out, slide_whistle(1400, 600, 0.35 / pace), 1.45 / pace, 0.2)
    return out


def western(n, key, pace):
    out = np.zeros(n)
    beat = 0.19 / pace
    for i, note in enumerate((40, 47, 52, 47, 45, 52, 40, 47, 43, 47, 50, 47)):
        place(out, pluck(note + key, 0.9, 0.55, 0.9965), i * beat, 0.4)
        place(out, pluck(note + key, 0.9, 0.55, 0.9965), i * beat + 0.11, 0.1)  # slapback
    return out


def news(n, key, pace):
    out = np.zeros(n)
    step = 0.1 / pace
    notes = (55, 55, 62, 55, 58, 55, 62, 60)
    for i in range(int(2.2 / step)):
        place(out, square(notes[i % 8] + key, step * 0.8, 0.5), i * step, 0.12)
    for at in (0.0, 0.8 / pace, 1.6 / pace):
        for note in (55, 58, 62, 67):
            place(out, brass(note + key, 0.35 / pace, 0.85), at, 0.18)
        place(out, timpani(43 + key, 0.9), at, 0.35)
    return out


def gameshow(n, key, pace):
    out = np.zeros(n)
    for rep in range(2):
        base = rep * 1.0 / pace
        for i, note in enumerate((67, 71, 74, 79)):
            place(out, organ(note + key, 0.14 / pace), base + i * 0.1 / pace, 0.35)
        for note in (67, 71, 74, 79):
            place(out, organ(note + key, 0.5 / pace), base + 0.4 / pace, 0.2)
        for i in range(2):
            place(out, bell(88 + key, 0.8, 0.9), base + 0.45 / pace + i * 0.16, 0.28)
    return out


def lounge(n, key, pace):
    out = np.zeros(n)
    beat = 0.2 / pace
    for i, note in enumerate((41, 45, 48, 50, 51, 50, 48, 45, 43, 46, 50, 53)):
        place(out, pluck(note + key, 0.5, 0.2, 0.994), i * beat, 0.45)
        place(out, brush(0.25), i * beat + beat / 2, 0.25)
    vib = np.arange(int(1.4 * SR)) / SR
    for at in (0.1, 1.3):
        for note in (65, 69, 72, 76):
            place(
                out,
                bell(note + key, 1.4, 1.0) * (1 + 0.3 * np.sin(2 * np.pi * 5.5 * vib)),
                at / pace,
                0.08,
            )
    return out


def sports(n, key, pace):
    out = norm(crowd(n / SR), 0.1)
    for at in (0.3, 1.4):
        m = int(0.5 * SR)
        tt = times(m)
        tone = np.sin(2 * np.pi * 2800 * tt) * (0.6 + 0.4 * np.sin(2 * np.pi * 28 * tt))
        place(out, tone * gate(m, 0.02, 0.05), at / pace, 0.05)
    for i, note in enumerate((60, 64, 67, 72, 67, 72)):
        place(out, organ(note + key, 0.16 / pace), 0.9 / pace + i * 0.17 / pace, 0.18)
    return out


def doowop(n, key, pace):
    out = np.zeros(n)
    trip = 0.14 / pace
    chords = ([60, 64, 67], [57, 60, 64], [53, 57, 60], [55, 59, 62])
    for c, chord in enumerate(chords):
        for i in range(3):
            for note in chord:
                place(out, piano(note + key, 0.5), (c * 3 + i) * trip, 0.2)
        place(out, pluck(chord[0] - 24 + key, 0.6, 0.25, 0.994), c * 3 * trip, 0.45)
        place(out, snare(), (c * 3 + 1) * trip, 0.15)
    return out


def movie(n, key, pace):
    out = np.zeros(n)
    place(out, strings([57 + key, 60 + key, 64 + key, 69 + key], n / SR), 0.0, 0.5)
    place(out, strings([45 + key], n / SR), 0.0, 0.4)
    place(out, timpani(33 + key, 1.2), 0.9 / pace, 0.3)
    return out


def rock(n, key, pace):
    out = np.zeros(n)
    beat = 0.24 / pace
    for i, root in enumerate((40, 40, 43, 45, 40, 40, 43, 38)):
        place(out, power_chord(root + key, beat * 1.1), i * beat, 0.3)
        place(out, kick() if i % 2 == 0 else snare(), i * beat, 0.35)
    return out


def kids(n, key, pace):
    out = np.zeros(n)
    beat = 0.22 / pace
    for i in range(10):
        for j, note in enumerate((67, 60, 64, 69)):  # a ukulele strum
            place(out, pluck(note + key, 0.5, 0.8, 0.993), i * beat + j * 0.012, 0.12)
    for i, note in enumerate((79, 81, 84, 81, 79, 76, 79, 84)):
        place(out, bell(note + key, 0.6, 0.35), 0.1 + i * beat, 0.16)
    return out


def disco(n, key, pace):
    out = np.zeros(n)
    beat = 0.24 / pace
    for i in range(10):
        place(out, kick(), i * beat, 0.45)
        place(out, hat(0.2, True), i * beat + beat / 2, 0.3)
        place(
            out, pluck((41 if i % 2 == 0 else 53) + key, beat, 0.6, 0.99), i * beat + beat / 2, 0.35
        )
    for at in (0.0, 4 * beat):
        place(out, strings([65 + key, 69 + key, 72 + key], 0.3, 0.02), at, 0.4)
    return out


def scifi(n, key, pace):
    out = np.zeros(n)
    m = n
    tt = times(m)
    glide = hz(72 + key) * 2 ** (0.6 * np.sin(2 * np.pi * 0.45 * pace * tt))
    f = glide * (1 + 0.012 * np.sin(2 * np.pi * 6 * tt))
    out += np.sin(osc(f, m)) * 0.25
    step = 0.12 / pace
    for i in range(int(2.2 / step)):
        place(out, square((48, 55, 60, 55)[i % 4] + key, step * 0.7, 0.4), i * step, 0.08)
    return out


def waltz(n, key, pace):
    out = np.zeros(n)
    beat = 0.2 / pace
    for bar in range(4):
        root = (48, 43, 48, 43)[bar]
        place(out, pluck(root + key, 0.5, 0.3, 0.994), bar * 3 * beat, 0.4)
        for b in (1, 2):
            for note in (64, 67, 72) if bar % 2 == 0 else (62, 65, 71):
                place(out, pluck(note + key, 0.3, 0.4, 0.99), (bar * 3 + b) * beat, 0.1)
    for i, note in enumerate((76, 79, 84, 83, 81, 79)):
        place(out, flute(note + key, beat * 1.9), i * beat * 2, 0.16)
    return out


def soap(n, key, pace):
    out = np.zeros(n)
    place(out, organ(57 + key, 1.2 / pace, 0.008), 0.0, 0.22)
    place(out, organ(60 + key, 1.2 / pace, 0.008), 0.0, 0.18)
    place(out, organ(64 + key, 1.2 / pace, 0.008), 0.0, 0.18)
    for note in (53, 57, 60, 65):
        place(out, organ(note + key, 1.1 / pace, 0.008), 1.2 / pace, 0.18)
    return out


def surf(n, key, pace):
    out = np.zeros(n)
    step = 0.055 / pace
    run = (64, 64, 64, 64, 63, 63, 63, 63, 62, 62, 62, 62, 61, 61, 61, 61, 59, 59, 59, 59)
    for i in range(int(2.2 / step)):
        note = run[i % len(run)] + key
        place(out, pluck(note, 0.25, 0.6, 0.992), i * step, 0.18)
    wet = np.zeros(n)
    place(wet, out, 0.07, 0.35)  # spring reverb, roughly
    return out + wet


SHOWS = {
    "fanfare": fanfare, "cartoon": cartoon, "western": western, "news": news,
    "gameshow": gameshow, "lounge": lounge, "sports": sports, "doowop": doowop,
    "movie": movie, "rock": rock, "kids": kids, "disco": disco, "scifi": scifi,
    "waltz": waltz, "soap": soap, "surf": surf,
}  # fmt: skip


# ------------------------------------------------------------ the TV itself


def tv_speaker(x: np.ndarray) -> np.ndarray:
    """A small TV's speaker: no deep bass, no sizzle, a little warmth."""
    y = band(x, 170, 5000, 1.2)
    y += 0.2 * band(x, 900, 1600)  # a touch of the cabinet
    return np.tanh(1.6 * y) / 1.6


def clunk() -> np.ndarray:
    """The channel knob clicking over a detent."""
    n = int(0.2 * SR)
    tt = times(n)
    click = band(rng.standard_normal(n), 900, 5000) * np.exp(-tt / rng.uniform(0.004, 0.007))
    f0 = rng.uniform(95, 120)
    thump = np.sin(2 * np.pi * f0 * tt * (1 - 0.3 * tt)) * np.exp(-tt / 0.035)
    rattle = np.zeros(n)
    k = int(rng.uniform(0.016, 0.028) * SR)
    rattle[k:] = band(rng.standard_normal(n - k), 1500, 6000) * np.exp(-tt[: n - k] / 0.004) * 0.4
    return 0.6 * click + 0.9 * thump + rattle


def static_noise(n: int) -> np.ndarray:
    """Soft static: pink-ish, rounded off at the top, gently fluttering."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec /= np.sqrt(np.maximum(f, 40))
    hiss = band(np.fft.irfft(spec, n), 250, rng.uniform(3600, 4600), 1.3)
    hiss /= np.abs(hiss).max()
    k = n // 480 + 2
    flutter = np.interp(times(n), np.arange(k) / 100, rng.standard_normal(k))
    return hiss * (1 + 0.15 * band(flutter, 0, 14))


def dial(length: int) -> list[tuple[float, str]]:
    """Where the knob stops, and what's there, ending with the fine tuning."""
    settle = {3: 0.55, 5: 0.8, 10: 1.2, 15: 1.4}[length]
    pool = list(SHOWS)
    rng.shuffle(pool)
    stops: list[tuple[float, str]] = [(0.0, "static")]
    at = rng.uniform(0.18, 0.28)
    since_static = 0
    while at < length - settle - 0.45:
        if since_static >= rng.integers(2, 4):
            stops.append((at, "static"))
            at += rng.uniform(0.14, 0.22)
            since_static = 0
            continue
        if not pool:  # heard them all: go round again, in a new order
            pool = [x for x in SHOWS if x != stops[-1][1]]
            rng.shuffle(pool)
        show = pool.pop()
        stops.append((at, show))
        long = length >= 10 and rng.random() < 0.2
        at += rng.uniform(0.95, 1.2) if long else rng.uniform(0.55, 0.85)
        since_static += 1
    stops.append((round(length - settle, 3), "tuning"))
    return [(round(a, 3), what) for a, what in stops]


def render(length: int, seed: int) -> tuple[np.ndarray, list[tuple[float, str]], float]:
    global rng
    rng = np.random.default_rng(seed)
    n = length * SR
    t = times(n)
    stops = dial(length)
    mix = np.zeros(n)
    static_level = np.zeros(n)
    ends = [s[0] for s in stops[1:]] + [float(length)]
    for (at, what), end in zip(stops, ends, strict=True):
        span = (t >= at) & (t < end)
        if what == "static":
            static_level[span] = 0.5
        elif what == "tuning":
            p = np.clip((t - at) / (end - at), 0, 1)
            static_level[span] = (0.5 * (1 - 0.8 * p))[span]
        else:
            key = int(rng.integers(-3, 4))
            pace = rng.uniform(0.92, 1.08)
            m = int(2.4 * SR)
            show = norm(SHOWS[what](m, key, pace))
            into = rng.uniform(0.15, max(0.2, 2.3 - (end - at) - 0.1))
            snippet = tv_speaker(show)[int(into * SR) : int((into + end - at) * SR)]
            snippet = snippet * gate(len(snippet), 0.03, 0.02)
            place(mix, snippet, at + 0.05, 0.9)
            static_level[span] = rng.uniform(0.1, 0.18)
            static_level[(t >= at) & (t < at + 0.05)] = 0.5  # passing between channels
    static_level = band(static_level, 0, 60)  # no clicks when it changes
    mix += static_noise(n) * static_level

    # The fine tuning: a soft whistle gliding down to nothing as it settles.
    tune_at = stops[-1][0]
    p = np.clip((t - tune_at - 0.05) / (length - tune_at - 0.1), 0, 1)
    top = rng.uniform(1400, 2000)
    whistle = np.sin(osc(top * (1 - p) ** 2 + 40, n))
    mix += 0.06 * whistle * np.sin(np.pi * p) ** 0.8 * (t > tune_at + 0.05)

    for at, _ in stops:
        place(mix, clunk(), at, 0.38)
        mix *= 1 - 0.85 * ((t >= at + 0.004) & (t < at + 0.028))  # sound drops as it changes

    # A small room, and a fade into the show.
    ir_n = int(0.9 * SR)
    ir = rng.standard_normal(ir_n) * np.exp(-times(ir_n) / 0.25)
    ir[:200] = 0
    ir /= np.sqrt((ir**2).sum())
    size = 1 << (n + ir_n).bit_length()
    wet = np.fft.irfft(np.fft.rfft(mix, size) * np.fft.rfft(ir, size), size)[:n]
    mix = mix + 0.15 * wet
    fade = min(0.5, length * 0.08)
    mix *= np.clip(t / 0.003, 0, 1) * np.clip((length - t) / fade, 0, 1) ** 0.7
    peak = float(np.abs(mix).max()) + 1e-9
    return mix / peak * 0.85, stops, peak


def landing() -> np.ndarray:
    """The knob clicking onto the station: a click, a burst of static that
    clears, and a short whistle as the fine tuning settles."""
    global rng
    rng = np.random.default_rng(4242)
    n = int(0.9 * SR)
    t = times(n)
    mix = np.zeros(n)
    place(mix, clunk(), 0.0, 0.38)
    mix += static_noise(n) * 0.5 * np.exp(-t / 0.18) * np.clip(t / 0.01, 0, 1)
    p = np.clip(t / 0.4, 0, 1)
    mix += 0.06 * np.sin(osc(1100 * (1 - p) ** 2 + 40, n)) * np.sin(np.pi * p) ** 0.8 * (t < 0.4)
    return mix * np.clip((0.9 - t) / 0.3, 0, 1)


def write(path: Path, mix: np.ndarray, gain: float | None = None) -> float:
    """To AAC, evened out to TARGET_LUFS (or by `gain`, in dB). Returns the
    gain it used."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "x.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((mix * 32767).astype("<i2").tobytes())
        if gain is None:
            measured = subprocess.run(
                ["ffmpeg", "-hide_banner", "-i", str(wav), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                capture_output=True, text=True, check=True,
            ).stderr  # fmt: skip
            stats = json.loads(measured[measured.rindex("{") :])
            gain = TARGET_LUFS - float(stats["input_i"])
            gain = min(gain, -1.5 - float(stats["input_tp"]))  # keep peaks under -1.5 dBTP
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(wav), "-af", f"volume={gain:.2f}dB",
             "-c:a", "aac", "-b:a", "96k", "-ar", "48000", str(path)],
            check=True,
        )  # fmt: skip
    return gain


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("tuning-*.m4a"):
        old.unlink()
    table: dict[str, list[dict]] = {}
    scales = []  # how much each file's mix was turned up, overall
    for length in LENGTHS:
        table[str(length)] = []
        for v in range(1, VARIANTS + 1):
            mix, stops, peak = render(length, seed=length * 100 + v)
            name = f"tuning-{length}-{v}.m4a"
            gain = write(OUT / name, mix)
            scales.append(0.85 / peak * 10 ** (gain / 20))
            table[str(length)].append(
                {"file": name, "clicks": [a for a, _ in stops], "stops": stops}
            )
            print(name, " ".join(f"{a:.2f}:{w}" for a, w in stops))
    (OUT / "dial.json").write_text(json.dumps(table, indent=1) + "\n")
    # The landing, at the same level as the dial sounds around it.
    scale = float(np.median(scales))
    mix = landing() * scale
    write(OUT / "landing.m4a", mix / 0.99 if np.abs(mix).max() > 0.99 else mix, gain=0.0)
    print("landing.m4a")


if __name__ == "__main__":
    main()
