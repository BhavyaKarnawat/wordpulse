"""Robust JavaScript <-> Python communication bridge for pywebview."""
import logging
import time
from typing import Any, Callable, Dict, Optional
from src.core.config import settings_to_dict
from src.models.settings import DisplayMode, DisplayStyle


class UIBridge:
    """API methods exposed directly to frontend JavaScript via window.pywebview.api."""

    def __init__(self):
        self._window = None
        self._on_style_change: Optional[Callable[[DisplayStyle], None]] = None
        self._on_mode_change: Optional[Callable[[DisplayMode], None]] = None
        self._on_always_on_top: Optional[Callable[[bool], None]] = None
        self._on_mock_toggle: Optional[Callable[[bool], None]] = None
        self._on_seek: Optional[Callable[[float], None]] = None
        self._on_toggle_playback: Optional[Callable[[], None]] = None
        self._on_next_track: Optional[Callable[[], None]] = None
        self._on_prev_track: Optional[Callable[[], None]] = None
        self._on_timing_offset_change: Optional[Callable[[int], None]] = None
        self.actions: Dict[str, Callable] = {}      # filled in by the coordinator
        self._runtime: Dict[str, Any] = {}
        self.beat_source: Optional[Callable[[], Dict[str, Any]]] = None
        self.on_save_tapped: Optional[Callable[[list], bool]] = None
        self.on_reset_tapped: Optional[Callable[[], bool]] = None

        # Cached in-memory snapshot for non-blocking client pulls
        self._state_version = 0
        self._cached_track: Dict[str, Any] = {}
        self._cached_lyrics: Dict[str, Any] = {}
        self._cached_palette: Dict[str, Any] = {}
        self._cached_settings: Dict[str, Any] = {}
        self._current_position: float = 0.0
        self._current_status: str = "STOPPED"
        self._current_track_id: str = ""
        self._measured_at: float = time.monotonic()
        self.last_poll: float = 0.0

    def set_window(self, window):
        self._window = window

    # Property accessors for coordinator wiring
    @property
    def on_style_change(self):
        return self._on_style_change

    @on_style_change.setter
    def on_style_change(self, callback):
        self._on_style_change = callback

    @property
    def on_mode_change(self):
        return self._on_mode_change

    @on_mode_change.setter
    def on_mode_change(self, callback):
        self._on_mode_change = callback

    @property
    def on_always_on_top(self):
        return self._on_always_on_top

    @on_always_on_top.setter
    def on_always_on_top(self, callback):
        self._on_always_on_top = callback

    @property
    def on_mock_toggle(self):
        return self._on_mock_toggle

    @on_mock_toggle.setter
    def on_mock_toggle(self, callback):
        self._on_mock_toggle = callback

    @property
    def on_seek(self):
        return self._on_seek

    @on_seek.setter
    def on_seek(self, callback):
        self._on_seek = callback

    @property
    def on_toggle_playback(self):
        return self._on_toggle_playback

    @on_toggle_playback.setter
    def on_toggle_playback(self, callback):
        self._on_toggle_playback = callback

    @property
    def on_next_track(self):
        return self._on_next_track

    @on_next_track.setter
    def on_next_track(self, callback):
        self._on_next_track = callback

    @property
    def on_prev_track(self):
        return self._on_prev_track

    @on_prev_track.setter
    def on_prev_track(self, callback):
        self._on_prev_track = callback

    @property
    def on_timing_offset_change(self):
        return self._on_timing_offset_change

    @on_timing_offset_change.setter
    def on_timing_offset_change(self, callback):
        self._on_timing_offset_change = callback

    # --- Methods called from Python to update internal state (NON-BLOCKING) ---

    def update_snapshot(self, track_info, lyrics_doc, palette, settings):
        """Updates internal snapshot data cleanly without evaluating blocking scripts."""
        self._state_version += 1

        self._cached_track = {
            "title": track_info.title,
            "artist": track_info.artist,
            "album": track_info.album,
            "display_title": track_info.display_title,
            "display_artist": track_info.display_artist,
            "duration": track_info.duration,
            "position": track_info.position,
            "status": track_info.status.value,
            "thumbnail_base64": track_info.thumbnail_base64,
            "track_id": track_info.track_id,
        }
        self._current_position = track_info.position
        self._measured_at = time.monotonic()
        self._current_status = track_info.status.value
        self._current_track_id = track_info.track_id

        lines_data = []
        for line in lyrics_doc.lines:
            words_data = [
                {"text": w.text, "start_time": w.start_time, "end_time": w.end_time, "icon": w.icon}
                for w in line.words
            ]
            lines_data.append({
                "text": line.text,
                "start_time": line.start_time,
                "end_time": line.end_time,
                "words": words_data,
            })

        self._cached_lyrics = {
            "track_title": lyrics_doc.track_title,
            "artist": lyrics_doc.artist,
            "is_synced": lyrics_doc.is_synced,
            "has_word_sync": lyrics_doc.has_word_sync,
            "source": getattr(lyrics_doc, "source", ""),
            "lines": lines_data,
        }

        self._cached_palette = {
            "background": palette.background,
            "highlight": palette.highlight,
            "accent": palette.accent,
            "surface": palette.surface,
        }

        self._cached_settings = dict(settings_to_dict(settings), **self._runtime)

    def push_settings(self, settings, runtime: Optional[Dict[str, Any]] = None) -> None:
        """Publishes changed settings and live state (hidden, battery, per-song offset) so the page re-syncs."""
        if runtime is not None:
            self._runtime = dict(runtime)
        self._cached_settings = dict(settings_to_dict(settings), **self._runtime)
        self._state_version += 1

    def update_playback_position(self, position: float, status_str: str, track_id: str):
        """Quickly updates current playback position and state."""
        self._current_position = position
        self._current_status = status_str
        self._current_track_id = track_id
        self._measured_at = time.monotonic()

    # --- Methods called from JavaScript (async promises) ---

    def get_state(self) -> Dict[str, Any]:
        """Called by JavaScript to retrieve full track, lyrics, palette, and settings."""
        return {
            "track": self._cached_track,
            "lyrics": self._cached_lyrics,
            "palette": self._cached_palette,
            "settings": self._cached_settings,
            "version": self._state_version,
        }

    def get_playback(self) -> Dict[str, Any]:
        """Fast lightweight poll for playback position and track identity."""
        self.last_poll = time.monotonic()      # the page is alive (watchdog)
        pos = self._current_position
        if self._current_status == "PLAYING":
            pos += time.monotonic() - self._measured_at  # position *now*, not when last measured
        beat = None
        if self.beat_source:
            try:
                beat = self.beat_source()
            except Exception:
                beat = None
        return {
            "beat": beat,
            "position": pos,
            "status": self._current_status,
            "track_id": self._current_track_id,
            "version": self._state_version,
        }

    def set_display_style(self, style_str: str) -> bool:
        try:
            style = DisplayStyle[style_str.upper()]
            if self._on_style_change:
                self._on_style_change(style)
            if self._cached_settings:
                self._cached_settings["display_style"] = style.value
            return True
        except Exception:
            return False

    def set_display_mode(self, mode_str: str) -> bool:
        try:
            mode = DisplayMode[mode_str.upper()]
            if self._on_mode_change:
                self._on_mode_change(mode)
            if self._cached_settings:
                self._cached_settings["display_mode"] = mode.value
            return True
        except Exception:
            return False

    def toggle_always_on_top(self, enable: bool) -> bool:
        if self._on_always_on_top:
            self._on_always_on_top(enable)
        if self._cached_settings:
            self._cached_settings["always_on_top"] = enable
        return True

    def toggle_mock_mode(self, is_mock: bool) -> bool:
        if self._on_mock_toggle:
            self._on_mock_toggle(is_mock)
        if self._cached_settings:
            self._cached_settings["mock_mode"] = is_mock
        return True

    def seek(self, position_sec: float) -> bool:
        if self._on_seek:
            self._on_seek(position_sec)
        self._current_position = position_sec
        self._measured_at = time.monotonic()
        return True

    def toggle_playback(self) -> bool:
        if self._on_toggle_playback:
            self._on_toggle_playback()
        return True

    def next_track(self) -> bool:
        if self._on_next_track:
            self._on_next_track()
        return True

    def prev_track(self) -> bool:
        if self._on_prev_track:
            self._on_prev_track()
        return True

    def save_word_timings(self, lines: list) -> bool:
        """From the tap-to-sync window: every line with its (partly tapped) word times."""
        return bool(self.on_save_tapped and self.on_save_tapped(lines))

    def reset_word_timings(self) -> bool:
        """Forget tapped timings for the current song and go back to the source lyrics."""
        return bool(self.on_reset_tapped and self.on_reset_tapped())

    # --- settings window / tray actions ---
    def _act(self, name: str, *args):
        fn = self.actions.get(name)
        if not fn:
            return None
        try:
            return fn(*args)
        except (ValueError, KeyError):
            raise                       # bad input: callers turn these into a friendly {"error": ...}
        except Exception as e:
            logging.getLogger("wordpulse").exception("Action %s failed", name)
            return {"error": f"{e.__class__.__name__}: {e}"}

    def report_error(self, message: str) -> bool:
        """JavaScript errors from the pages end up in the log (at most 20 a minute)."""
        now = time.monotonic()
        self._err_times = [t for t in getattr(self, "_err_times", []) if now - t < 60]
        if len(self._err_times) < 20:
            self._err_times.append(now)
            logging.getLogger("wordpulse").warning("Page error: %s", str(message)[:500])
        return True

    def quit_app(self) -> bool:
        self._act("exit_screensaver")       # same clean shutdown as the screensaver exit
        return True

    def get_settings_payload(self) -> Dict[str, Any]:
        return self._act("settings_payload") or {}

    def set_setting(self, name: str, value) -> Dict[str, Any]:
        try:
            return self._act("set_setting", name, value) or {}
        except (ValueError, KeyError) as e:
            return {"error": str(e)}

    def open_sync_window(self):
        self._act("open_sync")
        return True

    def search_lyrics(self, query: str = "") -> list:
        return self._act("search_lyrics", query) or []

    def use_lyrics(self, lrclib_id: int) -> bool:
        return bool(self._act("use_lyrics", lrclib_id))

    def import_lyrics(self, text: str) -> bool:
        return bool(self._act("import_lyrics", text))

    def open_logs(self) -> str:
        return self._act("open_logs") or ""

    def check_updates(self) -> Dict[str, Any]:
        return self._act("check_updates") or {}

    def song_offset(self, delta_ms: int) -> int:
        return self._act("song_offset", int(delta_ms)) or 0

    def reset_song_offset(self) -> int:
        return self._act("reset_song_offset") or 0

    def exit_screensaver(self) -> bool:
        self._act("exit_screensaver")
        return True

    def set_song_mood(self, mood: str) -> Dict[str, Any]:
        return self._act("song_mood", mood) or {}

    def welcome_action(self, name: str) -> bool:
        return bool(self._act("welcome", name))

    def open_settings(self) -> bool:
        self._act("open_settings")
        return True

    def close_settings(self) -> bool:
        return bool(self._act("close_settings"))

    def report_perf(self, stats: Dict[str, Any]) -> bool:
        """Frame-timing stats from the page; printed when WORDPULSE_DEBUG is set."""
        self.last_perf = stats
        import os
        if os.environ.get("WORDPULSE_DEBUG"):
            print(f"[perf] {stats}", flush=True)
            import logging
            logging.getLogger("wordpulse").info("[perf] %s", stats)
        return True

    def get_wallpaper(self) -> str:
        """The desktop wallpaper as a data URL (used behind the lyrics in desktop mode)."""
        from src.core.desktop import wallpaper_data_url
        if not getattr(self, "_wallpaper_cache", None):    # empty = not read yet, or reading failed
            self._wallpaper_cache = wallpaper_data_url()
        return self._wallpaper_cache

    def forget_wallpaper(self) -> None:
        """The wallpaper changed; the next get_wallpaper reads the new one."""
        self._wallpaper_cache = ""

    def adjust_timing_offset(self, delta_ms: int) -> bool:
        if self._on_timing_offset_change:
            self._on_timing_offset_change(delta_ms)
        return True
