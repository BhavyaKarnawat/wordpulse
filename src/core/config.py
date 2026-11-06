"""Saving and loading settings (and per-song timing) between runs.

Files live in %APPDATA%\\WordPulse:
  settings.json        - everything in AppSettings except runtime-only fields
  song_offsets.json    - {"artist - title": offset_ms}
"""
import json
import os
import re
import threading
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, Optional

from src.models.settings import (AUTO_MOOD, DEFAULT_MOOD_STYLES, FRAME_RATES, FULLSCREEN_BG, FULLSCREEN_LAYOUTS, VARIETY, AppSettings, DisplayMode, DisplayStyle,
                                 POSITIONS, REDUCE_MOTION, SHUFFLE_MODES, SLAB_SHAPES)

RUNTIME_ONLY = {"start_with_windows", "mock_mode", "window_opacity"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "WordPulse"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_to_dict(s: AppSettings, include_runtime: bool = True) -> Dict[str, Any]:
    out = {}
    for f in fields(s):
        if not include_runtime and f.name in RUNTIME_ONLY:
            continue
        v = getattr(s, f.name)
        out[f.name] = v.value if hasattr(v, "value") else (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v))
    return out


def coerce(name: str, value: Any, current: Any) -> Any:
    """Validates one setting value; raises ValueError when it doesn't fit."""
    if name == "display_style":
        return value if isinstance(value, DisplayStyle) else DisplayStyle[str(value).upper()]
    if name == "display_mode":
        return value if isinstance(value, DisplayMode) else DisplayMode[str(value).upper()]
    if name == "position" and value not in POSITIONS:
        raise ValueError(name)
    if name == "slab_shape" and value not in SLAB_SHAPES:
        raise ValueError(name)
    if name == "shuffle" and value not in SHUFFLE_MODES:
        raise ValueError(name)
    if name == "reduce_motion" and value not in REDUCE_MOTION:
        raise ValueError(name)
    if name == "auto_mood" and value not in AUTO_MOOD:
        raise ValueError(name)
    if name == "fullscreen_bg" and value not in FULLSCREEN_BG:
        raise ValueError(name)
    if name == "variety" and value not in VARIETY:
        raise ValueError(name)
    if name == "frame_rate" and value not in FRAME_RATES:
        raise ValueError(name)
    if name == "fullscreen_layout" and value not in FULLSCREEN_LAYOUTS:
        raise ValueError(name)
    if name == "mood_styles":
        # {mood: style or [styles]} -> {mood: [styles]}; an empty pool falls back to the default one
        if not isinstance(value, dict):
            raise ValueError(name)
        out = {k: list(v) for k, v in DEFAULT_MOOD_STYLES.items()}
        for mood, styles in value.items():
            if mood not in DEFAULT_MOOD_STYLES:
                continue
            items = styles if isinstance(styles, (list, tuple)) else [styles]
            pool = []
            for st in items:
                sid = DisplayStyle[str(st).upper()].value
                if sid not in pool:
                    pool.append(sid)
            out[mood] = pool or list(DEFAULT_MOOD_STYLES[mood])
        return out
    if name.endswith("_color"):
        if not isinstance(value, str) or not HEX.match(value):
            raise ValueError(name)
        return value.lower()
    if name == "shuffle_pool":
        pool = [DisplayStyle[str(v).upper()].value for v in value]
        if not pool:
            raise ValueError(name)
        return pool
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, int):
        v = int(value)
        limits = {"monitor": (-1, 16), "max_width_pct": (30, 95), "hide_when_paused_s": (0, 3600),
                  "timing_offset_ms": (-5000, 5000)}
        lo, hi = limits.get(name, (-10**6, 10**6))
        return max(lo, min(hi, v))
    if isinstance(current, float):
        v = float(value)
        limits = {"custom_x": (0.0, 1.0), "custom_y": (0.0, 1.0), "font_scale": (0.4, 1.8),
                  "wall_dim": (0.0, 0.8), "motion": (0.3, 1.5), "beat_strength": (0.0, 1.5)}
        lo, hi = limits.get(name, (-1e9, 1e9))
        return max(lo, min(hi, v))
    if isinstance(current, str):
        return str(value)[:200]
    return value


class ConfigStore:
    def __init__(self, directory: Optional[Path] = None):
        self.dir = Path(directory) if directory else config_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.dir / "settings.json"
        self.offsets_path = self.dir / "song_offsets.json"
        self.moods_path = self.dir / "song_moods.json"
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self.song_offsets: Dict[str, int] = self._read(self.offsets_path, {})
        self.song_moods: Dict[str, str] = self._read(self.moods_path, {})

    @staticmethod
    def _read(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _write(self, path: Path, data) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)   # atomic: a crash mid-write never leaves a broken file

    def load(self, base: Optional[AppSettings] = None) -> AppSettings:
        s = base or AppSettings()
        saved = self._read(self.settings_path, {})
        for f in fields(s):
            if f.name in RUNTIME_ONLY or f.name not in saved:
                continue
            try:
                setattr(s, f.name, coerce(f.name, saved[f.name], getattr(s, f.name)))
            except Exception:
                pass   # an unknown or broken value keeps the default
        return s

    def save(self, s: AppSettings) -> bool:
        """Writes settings; on failure (disk full, folder locked...) logs once and keeps running."""
        try:
            with self._lock:
                self._write(self.settings_path, settings_to_dict(s, include_runtime=False))
            self.save_failed = False
            return True
        except OSError as e:
            if not getattr(self, "save_failed", False):
                import logging
                logging.getLogger("wordpulse").error("Couldn't save settings (%s); they'll apply until you quit", e)
            self.save_failed = True
            return False

    def save_soon(self, s: AppSettings, delay: float = 0.6) -> None:
        """Debounced save, so dragging a slider doesn't hammer the disk."""
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(delay, self.save, args=(s,))
            self._timer.daemon = True
            self._timer.start()

    # ---- per-song timing ----
    @staticmethod
    def song_key(title: str, artist: str) -> str:
        return f"{artist} - {title}".strip().lower()

    def get_song_offset(self, title: str, artist: str) -> int:
        return int(self.song_offsets.get(self.song_key(title, artist), 0))

    def get_song_mood(self, title: str, artist: str) -> str:
        return self.song_moods.get(self.song_key(title, artist), "")

    def set_song_mood(self, title: str, artist: str, mood: str) -> str:
        key = self.song_key(title, artist)
        if mood:
            self.song_moods[key] = mood
        else:
            self.song_moods.pop(key, None)
        with self._lock:
            self._write(self.moods_path, self.song_moods)
        return mood

    def set_song_offset(self, title: str, artist: str, ms: int) -> int:
        ms = max(-5000, min(5000, int(ms)))
        key = self.song_key(title, artist)
        if ms == 0:
            self.song_offsets.pop(key, None)
        else:
            self.song_offsets[key] = ms
        with self._lock:
            self._write(self.offsets_path, self.song_offsets)
        return ms
