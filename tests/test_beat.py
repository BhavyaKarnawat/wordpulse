"""The beat tracker against generated drum patterns of known tempo (no real audio needed)."""
import numpy as np
import pytest

from src.audio.beat import BeatTracker

SR = 48000


def drum_track(bpm, seconds=12.0, swing_hats=True, noise=0.02, seed=0):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    out = rng.normal(0, noise, n).astype(np.float32)          # a bed of noise, like a mix
    period = 60.0 / bpm
    t = np.arange(int(SR * 0.12)) / SR
    kick = (np.sin(2 * np.pi * 60 * t) * np.exp(-t * 30)).astype(np.float32)
    hat = (rng.normal(0, 1, int(SR * 0.03)) * np.exp(-np.arange(int(SR * 0.03)) / SR * 120)).astype(np.float32) * 0.25
    beat = 0
    while beat * period < seconds - 0.2:
        i = int(beat * period * SR)
        out[i:i + len(kick)] += kick * (1.0 if beat % 2 == 0 else 0.8)
        if swing_hats:
            j = int((beat + 0.5) * period * SR)
            if j + len(hat) < n:
                out[j:j + len(hat)] += hat
        beat += 1
    return np.clip(out, -1, 1)


def run(track, block=4800):
    bt = BeatTracker(sr=SR)
    for k in range(0, len(track), block):
        chunk = track[k:k + block]
        bt.feed(chunk, end_time=(k + len(chunk)) / SR)
    return bt


@pytest.mark.parametrize("bpm", [75, 92, 120, 128, 140, 174])
def test_tempo_found(bpm):
    bt = run(drum_track(bpm))
    detected = bt.bpm
    # allow the classic half/double ambiguity only at the extremes the prior can't settle
    ok = abs(detected - bpm) / bpm < 0.03
    assert ok, f"expected ~{bpm}, got {detected:.1f}"
    assert bt.confidence > 0.2


def test_beat_phase_lands_on_kicks():
    bpm = 120
    bt = run(drum_track(bpm, seconds=10))
    now = 10.0
    lb = bt.last_beat(now)
    period = 60.0 / bpm
    # kicks are at multiples of the period; predicted beat must be within 30 ms of one
    off = (lb % period)
    assert min(off, period - off) < 0.03, f"beat off by {min(off, period - off) * 1000:.0f} ms"


def test_volume_does_not_change_tempo():
    track = drum_track(128)
    loud, quiet = run(track), run(track * 0.05)
    assert abs(loud.bpm - quiet.bpm) < 1.5


def test_silence_has_no_confidence():
    bt = run(np.zeros(SR * 6, dtype=np.float32))
    assert bt.confidence < 0.1


def test_busy_bright_music_has_more_energy():
    calm = run(drum_track(75, swing_hats=False))
    busy = run(drum_track(140, swing_hats=True, noise=0.05))
    assert busy.energy() > calm.energy()
