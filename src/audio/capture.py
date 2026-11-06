"""Listens to what Windows is playing (WASAPI loopback) and feeds the beat tracker.

The audio never leaves this process: it is analysed in memory, ~21 ms at a time,
and thrown away. Capture only runs while `active` is True (the coordinator sets
that while a music app reports it's playing), so notifications and videos while
you're paused are ignored and no CPU is spent.
"""
import logging
import threading
import time
from typing import Optional

import numpy as np

from src.audio.beat import BeatTracker

log = logging.getLogger("wordpulse")

try:
    import pyaudiowpatch as pyaudio
    HAS_AUDIO = True
except Exception:          # library missing (or not Windows): mood falls back to lyrics + tags
    pyaudio = None
    HAS_AUDIO = False


class AudioAnalyzer:
    def __init__(self):
        self.active = False
        self.available = HAS_AUDIO
        self.status = "off" if HAS_AUDIO else "unavailable"
        self.device_name = ""
        self.tracker: Optional[BeatTracker] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.listened_s = 0.0          # seconds of audio analysed for the current song

    def start(self):
        if not HAS_AUDIO or self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="audio")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread = None

    def reset(self):
        """New song: forget the old tempo."""
        with self._lock:
            if self.tracker:
                self.tracker = BeatTracker(sr=self.tracker.sr)
            self.listened_s = 0.0

    def snapshot(self) -> dict:
        with self._lock:
            if not self.tracker or not self.active:
                return {"bpm": 0, "confidence": 0, "beat_age": None, "period": 0, "energy": 0,
                        "harshness": 0, "brightness": 0, "drop_age": None, "status": self.status,
                        "listened_s": round(self.listened_s, 1)}
            snap = self.tracker.snapshot(time.monotonic())
        snap["status"] = self.status
        snap["listened_s"] = round(self.listened_s, 1)
        return snap

    # ------------------------------------------------------------------ capture loop
    def _run(self):
        pa = None
        delay, last_problem = 0.0, ""
        while not self._stop.is_set():
            if not self.active:
                self.status = "paused"
                time.sleep(0.3)
                continue
            try:
                pa = pa or pyaudio.PyAudio()
                dev = pa.get_default_wasapi_loopback()
                sr = int(dev["defaultSampleRate"])
                ch = max(1, int(dev["maxInputChannels"]))
                self.device_name = dev["name"]
                hop = 1024
                with self._lock:
                    if not self.tracker or self.tracker.sr != sr:
                        self.tracker = BeatTracker(sr=sr, hop=hop)
                stream = pa.open(format=pyaudio.paFloat32, channels=ch, rate=sr, input=True,
                                 input_device_index=dev["index"], frames_per_buffer=hop)
                self.status = "listening"
                if last_problem:
                    log.info("Audio output is back")
                delay, last_problem = 0.0, ""
                log.info("Beat detection listening on %s (%d Hz)", self.device_name, sr)
                try:
                    while self.active and not self._stop.is_set():
                        # Windows sends nothing at all while the output is silent; don't block on it
                        if stream.get_read_available() < hop:
                            time.sleep(0.01)
                            continue
                        raw = stream.read(hop, exception_on_overflow=False)
                        now = time.monotonic()
                        block = np.frombuffer(raw, dtype=np.float32)
                        mono = block.reshape(-1, ch).mean(axis=1) if ch > 1 else block
                        with self._lock:
                            self.tracker.feed(mono, now)
                            self.listened_s += len(mono) / sr
                finally:
                    stream.stop_stream()
                    stream.close()
            except Exception as e:
                # no output device, device unplugged or switched: retry with growing gaps, log once
                from src.core.system import next_backoff
                problem = f"{e.__class__.__name__}: {e}"
                self.status = "no-device" if "loopback" in str(e).lower() or "device" in str(e).lower() else "error"
                if problem != last_problem:
                    log.warning("Audio capture problem (%s); will keep retrying quietly", problem)
                    last_problem = problem
                delay = next_backoff(delay)
                try:
                    if pa:
                        pa.terminate()
                except Exception:
                    pass
                pa = None
                self._stop.wait(delay)
        if pa:
            try:
                pa.terminate()
            except Exception:
                pass
        self.status = "off"
