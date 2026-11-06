"""Harder generated material: swing, syncopation, trap hats, tempo changes, intros, ballads, noise."""
import numpy as np
import pytest

from src.audio.beat import BeatTracker

SR = 48000
RNG = np.random.default_rng(7)


def _kick():
    t = np.arange(int(SR * 0.15)) / SR
    return (np.sin(2 * np.pi * (50 + 60 * np.exp(-t * 40)) * t) * np.exp(-t * 22)).astype(np.float32)


def _snare():
    n = int(SR * 0.12)
    t = np.arange(n) / SR
    return ((RNG.normal(0, 1, n) * 0.5 + np.sin(2 * np.pi * 190 * t)) * np.exp(-t * 30)).astype(np.float32) * 0.6


def _hat(length=0.03, gain=0.18):
    n = int(SR * length)
    return (RNG.normal(0, 1, n) * np.exp(-np.arange(n) / SR * 140)).astype(np.float32) * gain


def _note(freq, length=0.9, attack=0.03, gain=0.35):
    n = int(SR * length)
    t = np.arange(n) / SR
    env = np.minimum(1, t / attack) * np.exp(-t * 2.5)
    return (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)).astype(np.float32) * env.astype(np.float32) * gain


def place(out, sample, at_s):
    i = int(at_s * SR)
    if 0 <= i < len(out):
        j = min(len(out), i + len(sample))
        out[i:j] += sample[:j - i]


def bed(seconds, noise=0.02):
    return RNG.normal(0, noise, int(SR * seconds)).astype(np.float32)


def run(track, block=4800):
    bt = BeatTracker(sr=SR)
    history = []
    for k in range(0, len(track), block):
        chunk = track[k:k + block]
        bt.feed(chunk, end_time=(k + len(chunk)) / SR)
        history.append(((k + len(chunk)) / SR, bt.bpm))
    return bt, history


def near(a, b, tol=0.04):
    return b and abs(a - b) / b < tol


def octave_ok(detected, bpm):
    return any(near(detected, bpm * m) for m in (0.5, 1, 2))


# ---------------------------------------------------------------- patterns
def swing(bpm=100, seconds=14):
    out, p = bed(seconds), 60 / bpm
    for b in range(int(seconds / p)):
        t = b * p
        place(out, _kick(), t) if b % 2 == 0 else place(out, _snare(), t)
        place(out, _hat(), t)
        place(out, _hat(gain=0.12), t + p * 2 / 3)        # swung eighth
    return out


def syncopated(bpm=120, seconds=14):
    out, p = bed(seconds), 60 / bpm
    for bar in range(int(seconds / (4 * p))):
        t0 = bar * 4 * p
        for k in (0, 1.5, 2.5):                           # kick on 1, the "and" of 2, the "and" of 3
            place(out, _kick(), t0 + k * p)
        for k in (1, 3):
            place(out, _snare(), t0 + k * p)
        for e in range(8):
            place(out, _hat(), t0 + e * p / 2)
    return out


def trap(bpm=140, seconds=14):
    """Half-time trap: kick on 1, snare on 3, rattling 1/16 hats (with triplet rolls)."""
    out, p = bed(seconds), 60 / bpm
    for bar in range(int(seconds / (4 * p))):
        t0 = bar * 4 * p
        place(out, _kick(), t0)
        place(out, _kick(), t0 + 2.75 * p)
        place(out, _snare(), t0 + 2 * p)
        for s in range(16):
            place(out, _hat(0.02, 0.12), t0 + s * p / 4)
        for s in range(6):                                # a triplet roll at the end of the bar
            place(out, _hat(0.015, 0.1), t0 + 3 * p + s * p / 6)
    return out


def house(bpm=124, seconds=14):
    out, p = bed(seconds), 60 / bpm
    for b in range(int(seconds / p)):
        t = b * p
        place(out, _kick(), t)
        place(out, _hat(0.08, 0.2), t + p / 2)            # open hat on the off-beat
        if b % 2:
            place(out, _snare() * 0.6, t)
    return out


def ballad(bpm=66, seconds=20):
    out, p = bed(seconds, 0.005), 60 / bpm
    chord = [220, 277, 330, 247]
    for b in range(int(seconds / p)):
        place(out, _note(chord[b % 4], length=p * 1.2), b * p)
        if b % 2:
            place(out, _note(chord[b % 4] * 2, length=p * 0.6, gain=0.15), b * p + p / 2)
    return out


# ---------------------------------------------------------------- tests
def test_swing():
    bt, _ = run(swing(100))
    assert near(bt.bpm, 100), bt.bpm


def test_syncopated_kicks():
    bt, _ = run(syncopated(120))
    assert near(bt.bpm, 120), bt.bpm


def test_trap_half_time_is_an_octave_of_the_real_tempo():
    # 70 vs 140 is genuinely ambiguous for trap; the mood step doubles it using lyric density
    bt, _ = run(trap(140))
    assert octave_ok(bt.bpm, 140), bt.bpm


def test_four_on_the_floor_house():
    bt, _ = run(house(124))
    assert near(bt.bpm, 124), bt.bpm


def test_drumless_ballad():
    bt, _ = run(ballad(66))
    assert octave_ok(bt.bpm, 66), bt.bpm


def test_quiet_intro_then_drums():
    track = np.concatenate([bed(5, 0.003), house(124, 12)])
    bt, _ = run(track)
    assert near(bt.bpm, 124), bt.bpm


def test_tempo_change_is_followed():
    track = np.concatenate([house(100, 12), house(130, 16)])
    bt, history = run(track)
    assert near(bt.bpm, 130), bt.bpm
    # and it doesn't take forever: settled on 130 within 10 s of the change
    settled = next((t for t, b in history if t > 12 and near(b, 130)), None)
    assert settled is not None and settled - 12 < 10, settled


def test_heavy_noise_bed():
    track = house(124, 14) + RNG.normal(0, 0.12, int(SR * 14)).astype(np.float32)
    bt, _ = run(np.clip(track, -1, 1))
    assert near(bt.bpm, 124), bt.bpm
