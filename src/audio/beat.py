"""Tempo, beat and energy analysis on a stream of mono audio (numpy only).

How it works:
  1. Every hop (~21 ms) we take an FFT and measure *spectral flux*: how much
     louder each frequency got since the last hop. Drum hits and note onsets
     show up as spikes. Low frequencies (kick drum) get extra weight.
  2. Every second we autocorrelate the last 8 s of that onset curve. Repeating
     beats make peaks at the beat period. A gentle preference for ~120 BPM
     breaks ties between half- and double-time.
  3. The beat *phase* is the offset whose comb of beats lines up best with the
     onset curve; from it we predict when the next beats land.
Everything is relative (flux is normalised), so it works at any volume.
"""
from collections import deque
from typing import Deque, List, Optional

import numpy as np


class BeatTracker:
    MIN_BPM, MAX_BPM = 60.0, 200.0

    def __init__(self, sr: int = 48000, hop: int = 1024, win: int = 2048, history_s: float = 8.0):
        self.sr, self.hop, self.win = sr, hop, win
        self.fps = sr / hop
        self.window = np.hanning(win).astype(np.float32)
        self.buf = np.zeros(win, dtype=np.float32)
        freqs = np.fft.rfftfreq(win, 1.0 / sr)
        self.freqs = freqs
        self.weights = np.where(freqs < 150, 3.0, np.where(freqs < 4000, 1.0, 0.5)).astype(np.float32)
        self.harsh_band = (freqs >= 2000) & (freqs < 8000)
        self.low_band = freqs < 200          # kick drum: where the beat usually lives
        self.prev = None
        n = int(self.fps * history_s)
        self.env: Deque[float] = deque(maxlen=n)
        self.low_env: Deque[float] = deque(maxlen=n)
        self.frame_times: Deque[float] = deque(maxlen=n)   # clock time at the end of each hop
        self.rms_hist: Deque[float] = deque(maxlen=n)
        self._pending = np.zeros(0, dtype=np.float32)
        self._since_tempo = 0

        self.bpm = 0.0
        self.confidence = 0.0
        self.period = 0.0                 # seconds
        self.beat_ref: Optional[float] = None   # clock time of a beat
        self._candidate = None
        self._candidate_hits = 0
        self.brightness = 0.0             # spectral centroid, 0..1
        self.harshness = 0.0              # share of energy in 2-8 kHz
        self.onset_rate = 0.0             # strong onsets per second
        self.loud_db = -90.0
        self.last_drop: Optional[float] = None

    # ------------------------------------------------------------------ input
    def feed(self, mono: np.ndarray, end_time: float) -> None:
        """mono: float samples in -1..1; end_time: clock time of the last sample."""
        data = np.concatenate([self._pending, mono.astype(np.float32)])
        n_hops = len(data) // self.hop
        for i in range(n_hops):
            chunk = data[i * self.hop:(i + 1) * self.hop]
            remaining = len(data) - (i + 1) * self.hop
            self._hop(chunk, end_time - remaining / self.sr)
        self._pending = data[n_hops * self.hop:]

    def _hop(self, chunk: np.ndarray, t: float) -> None:
        self.buf = np.roll(self.buf, -self.hop)
        self.buf[-self.hop:] = chunk
        mag = np.abs(np.fft.rfft(self.buf * self.window))
        logmag = np.log1p(100.0 * mag)
        if self.prev is None:
            self.prev = logmag
        rise = np.maximum(0.0, logmag - self.prev)
        flux = float(np.sum(rise * self.weights))
        low_flux = float(np.sum(rise[self.low_band]))
        self.prev = logmag

        rms = float(np.sqrt(np.mean(chunk * chunk)) + 1e-9)
        self.env.append(flux)
        self.low_env.append(low_flux)
        # an onset shows up once it is inside the FFT window; date the frame at the window centre
        self.frame_times.append(t - (self.win / 2) / self.sr)
        self.rms_hist.append(20 * np.log10(rms))

        total = float(np.sum(mag)) + 1e-9
        a = 0.05
        self.brightness = (1 - a) * self.brightness + a * float(np.sum(self.freqs * mag) / total / 6000.0)
        self.harshness = (1 - a) * self.harshness + a * float(np.sum(mag[self.harsh_band]) / total)

        self._since_tempo += 1
        if self._since_tempo >= int(self.fps) and len(self.env) >= int(self.fps * 4):
            self._since_tempo = 0
            self._estimate()

    # ------------------------------------------------------------------ analysis
    def _onset_curve(self, source=None) -> np.ndarray:
        e = np.asarray(self.env if source is None else source, dtype=np.float64)
        k = max(3, int(self.fps * 0.4))
        local = np.convolve(e, np.ones(k) / k, mode="same")
        e = np.maximum(0.0, e - local)          # keep only the spikes above the local level
        sd = e.std()
        return e / sd if sd > 1e-9 else e

    def _estimate(self) -> None:
        e = self._onset_curve()
        n = len(e)
        if not np.any(e):
            self.confidence = 0.0
            return
        def autocorr(x):
            spec = np.fft.rfft(x, n=2 * n)
            r = np.fft.irfft(spec * np.conj(spec))[:n]
            return r / (r[0] + 1e-9)

        ac = autocorr(e)
        # off-beat hi-hats make every half-beat look like a beat; the kick-only curve
        # repeats on the real beat, so let it vote too (skipped when there's no bass, e.g. piano)
        low_curve = self._onset_curve(self.low_env)
        if np.any(low_curve) and low_curve.std() > 0:
            ac = 0.7 * ac + 0.3 * autocorr(low_curve)

        def at(lag):  # linear interpolation
            if lag < 1 or lag >= n - 1:
                return 0.0
            i = int(lag)
            f = lag - i
            return ac[i] * (1 - f) + ac[i + 1] * f

        bpms = np.arange(self.MIN_BPM, self.MAX_BPM + 0.01, 0.5)
        scores = []
        for b in bpms:
            lag = 60.0 * self.fps / b
            s = at(lag) + 0.5 * at(2 * lag) + 0.25 * at(3 * lag)
            prior = np.exp(-0.5 * (np.log2(b / 120.0) / 0.9) ** 2)
            scores.append(s * prior)
        scores = np.asarray(scores)
        best = int(np.argmax(scores))
        bpm = float(bpms[best])
        # contrast between the winning period and the typical score = how sure we are
        conf = float(np.clip((scores[best] - np.median(scores)) / (scores[best] + 1e-9), 0, 1))

        # hysteresis: a different tempo has to win twice in a row before we switch
        if self.bpm and abs(bpm - self.bpm) / self.bpm < 0.04:
            self.bpm = 0.7 * self.bpm + 0.3 * bpm
        elif self._candidate and abs(bpm - self._candidate) / self._candidate < 0.04:
            self._candidate_hits += 1
            if self._candidate_hits >= 2 or not self.bpm:
                self.bpm, self._candidate, self._candidate_hits = bpm, None, 0
        else:
            self._candidate, self._candidate_hits = bpm, 1
            if not self.bpm:
                self.bpm = bpm
        self.confidence = 0.6 * self.confidence + 0.4 * conf
        self.period = 60.0 / self.bpm

        # phase: offset whose comb of beats collects the most *bass* onset energy
        # (hi-hats often sit between beats; kicks mark the beat itself)
        low = self._onset_curve(self.low_env)
        if np.any(low):
            e = 0.8 * low + 0.2 * e
        p = self.period * self.fps
        best_phase, best_sum = 0.0, -1.0
        for ph in np.arange(0, p, 0.5):
            idx = np.arange(n - 1 - ph, -1, -p).astype(int)
            s = float(e[idx].sum())
            if s > best_sum:
                best_sum, best_phase = s, ph
        times = list(self.frame_times)
        self.beat_ref = times[int(n - 1 - best_phase)] if n - 1 - best_phase >= 0 else times[-1]

        # loudness / drops / onset density
        r = np.asarray(self.rms_hist)
        self.loud_db = float(np.median(r[-int(self.fps):]))
        short = float(np.mean(r[-int(self.fps * 0.5):]))
        long_ = float(np.mean(r[:-int(self.fps)])) if len(r) > self.fps * 2 else short
        if short - long_ > 6.0 and short > -45:
            self.last_drop = times[-1]
        peaks = (e[1:-1] > 2.0) & (e[1:-1] >= e[:-2]) & (e[1:-1] >= e[2:])
        self.onset_rate = float(peaks.sum()) / (n / self.fps)

    # ------------------------------------------------------------------ output
    def last_beat(self, now: float) -> Optional[float]:
        """Clock time of the most recent beat at or before `now` (predicted from tempo + phase)."""
        if not self.beat_ref or not self.period:
            return None
        k = np.floor((now - self.beat_ref) / self.period)
        return self.beat_ref + k * self.period

    def energy(self) -> float:
        """0..1, volume-independent: how busy and bright the music is."""
        return float(np.clip(0.55 * min(1.0, self.onset_rate / 5.0) + 0.45 * min(1.0, self.harshness * 3.0), 0, 1))

    def snapshot(self, now: float) -> dict:
        lb = self.last_beat(now)
        return {
            "bpm": round(self.bpm, 1) if self.bpm else 0,
            "confidence": round(self.confidence, 2),
            "beat_age": round(now - lb, 4) if lb is not None else None,
            "period": round(self.period, 4) if self.period else 0,
            "energy": round(self.energy(), 2),
            "harshness": round(self.harshness, 3),
            "brightness": round(self.brightness, 3),
            "drop_age": round(now - self.last_drop, 2) if self.last_drop else None,
            "loud_db": round(self.loud_db, 1),
        }
