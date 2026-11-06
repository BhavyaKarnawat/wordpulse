"""Central application coordinator connecting UI, media providers, lyrics, tray and settings."""
import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from src.core import autostart
from src.core.bridge import UIBridge
from src.core.config import ConfigStore, coerce, settings_to_dict
from src.core.desktop import DesktopPinner, primary_screen_size
from src.core.palette import PaletteExtractor
from src.core.power import PowerManager
from src.core import system
from src.core.mood import MOODS, MOOD_LABELS, GenreTags, classify, word_rate
from src.audio.capture import AudioAnalyzer
from src.lyrics.service import LyricsService
from src.media.gsmtc_provider import GSMTCMediaProvider
from src.media.mock_provider import MockMediaProvider
from src.models.lyrics import LyricLine, LyricsDocument, LyricWord
from src.models.settings import AppSettings, DisplayMode, DisplayStyle
from src.models.theme import PaletteTheme
from src.models.track import PlaybackStatus, TrackInfo
from src.version import APP_VERSION

try:
    import webview
    HAS_WEBVIEW = True
except ImportError:
    HAS_WEBVIEW = False

log = logging.getLogger("wordpulse")
UI_DIR = Path(__file__).parent.parent / "ui"

STYLE_LABELS = {
    "SHIP": "Ship", "FISHEYE": "Fisheye", "FISHEYE_VISUAL": "Fisheye Visual", "VISUAL": "Visual",
    "POP": "Pop", "STAMP": "Stamp", "LINE": "Line", "ORBIT": "Orbit",
    "INKBLOT": "Inkblot", "SQUEEZE": "Squeeze", "REMOLD": "Remold",
    "CONSTELLATION": "Constellation", "BRANCHES": "Branches", "WEB": "Web",
    "CODE": "Code", "CODE_VISUAL": "Code Visual",
}
FONTS = ["Segoe UI Variable Display", "Segoe UI", "Bahnschrift", "Arial Black", "Impact",
         "Georgia", "Cascadia Code", "Trebuchet MS", "Verdana", "Comic Sans MS"]


class AppCoordinator:
    """Coordinates lifecycle, polling loops, media synchronization, settings and UI."""

    def __init__(self, settings: Optional[AppSettings] = None, config: Optional[ConfigStore] = None,
                 screensaver: bool = False):
        self.config = config                      # None in tests: nothing is written to disk
        self.settings = settings or AppSettings()
        self.screensaver = screensaver
        self.bridge = UIBridge()
        self.palette_extractor = PaletteExtractor()
        self.power_manager = PowerManager()
        self.lyrics_service = LyricsService()

        self.mock_provider = MockMediaProvider()
        self.gsmtc_provider = GSMTCMediaProvider()
        self._apply_player_prefs()

        self.current_track: Optional[TrackInfo] = None
        self.current_doc: Optional[LyricsDocument] = None
        self.current_palette: Optional[PaletteTheme] = None

        # live state the page needs besides settings
        self.runtime = {"hidden": False, "on_battery": False, "song_offset_ms": 0,
                        "mood": "", "mood_reason": "", "mood_bpm": 0, "mood_source": "", "audio": "off",
                        "system_reduce_motion": system.system_reduce_motion(), "screensaver": screensaver}
        self.dnd = False
        self._paused_since: Optional[float] = None
        self.known_players: list = []
        self._players_at = 0.0
        self.on_status: Optional[Callable[[str], None]] = None   # tray tooltip
        self.on_notify: Optional[Callable[[str, str], None]] = None  # tray balloon
        self.hotkeys: Optional[system.HotkeyListener] = None
        self.log_dir: Optional[Path] = None

        self.is_running = False
        self._poll_thread: Optional[threading.Thread] = None
        self.window = None
        self.settings_window = None
        self._sync_window = None
        self.pinner = DesktopPinner()
        self.extra_windows: list = []      # (window, pinner) per extra monitor in "All displays"
        self.audio = AudioAnalyzer()
        self.genre = GenreTags(config.dir / "genre_tags.json" if config else None)
        self._mood_started = 0.0
        self._tags: list = []
        self.bridge.beat_source = self._beat_snapshot

        self._setup_bridge_handlers()
        self.push()

    # ------------------------------------------------------------------ plumbing
    @property
    def media_provider(self):
        return self.mock_provider if self.settings.mock_mode else self.gsmtc_provider

    def _setup_bridge_handlers(self):
        b = self.bridge
        b.on_style_change = self.set_display_style
        b.on_mode_change = self.set_display_mode
        b.on_always_on_top = self.set_always_on_top
        b.on_mock_toggle = self.toggle_mock_mode
        b.on_seek = self.seek
        b.on_toggle_playback = self.toggle_playback
        b.on_next_track = self.next_track
        b.on_prev_track = self.prev_track
        b.on_timing_offset_change = self.adjust_song_offset
        b.on_save_tapped = self.save_tapped_timings
        b.on_reset_tapped = self.reset_tapped_timings
        b.actions.update({
            "set_setting": self.set_setting,
            "settings_payload": self.settings_payload,
            "open_sync": self.open_sync_window,
            "search_lyrics": self.search_lyrics,
            "use_lyrics": self.use_lyrics,
            "import_lyrics": self.import_lyrics,
            "open_logs": self.open_logs,
            "check_updates": self.check_updates,
            "song_offset": self.adjust_song_offset,
            "reset_song_offset": self.reset_song_offset,
            "exit_screensaver": self.quit,
            "close_settings": self.close_settings_window,
            "song_mood": self.set_song_mood,
            "welcome": self.welcome_action,
        })

    def push(self):
        self.bridge.push_settings(self.settings, self.runtime)

    def save(self):
        if self.config:
            self.config.save_soon(self.settings)

    def _apply_player_prefs(self):
        self.gsmtc_provider.preferred_player = self.settings.preferred_player
        self.gsmtc_provider.ignore_browsers = self.settings.ignore_browsers

    # ------------------------------------------------------------------ settings
    def set_setting(self, name: str, value):
        """One entry point for every change from the settings window or tray."""
        if name == "start_with_windows":
            try:
                self.settings.start_with_windows = autostart.set_enabled(bool(value))
            except OSError:
                log.exception("Could not change start-with-Windows")
            return self.settings_payload()
        if not hasattr(self.settings, name):
            raise ValueError(f"unknown setting {name}")
        value = coerce(name, value, getattr(self.settings, name))

        if name == "display_mode":
            self.set_display_mode(value)
        elif name == "display_style":
            self.set_display_style(value)
        elif name == "always_on_top":
            self.set_always_on_top(value)
        else:
            setattr(self.settings, name, value)
            if name == "monitor":
                self._reposition()
                self._sync_extra_windows()
            elif name in ("preferred_player", "ignore_browsers"):
                self._apply_player_prefs()
                self.current_track = None          # re-pick the session on the next poll
            elif name == "hotkeys_enabled":
                self._start_hotkeys() if value else self._stop_hotkeys()
            elif name == "auto_theme" and self.current_track:
                self._refresh_palette()
            self.push()
        self.save()
        return self.settings_payload()

    def set_display_style(self, style: DisplayStyle):
        self.settings.display_style = style
        self.push()
        self.save()

    def next_style(self):
        styles = list(DisplayStyle)
        i = styles.index(self.settings.display_style)
        self.set_display_style(styles[(i + 1) % len(styles)])

    def set_always_on_top(self, enable: bool):
        self.settings.always_on_top = enable
        self.push()
        self.save()
        if self.window and HAS_WEBVIEW and self.settings.display_mode != DisplayMode.DESKTOP_WALLPAPER:
            try:
                self.window.on_top = enable
            except Exception:
                pass

    def toggle_dnd(self):
        self.dnd = not self.dnd
        self._update_hidden()

    def _window_hwnd(self) -> int:
        try:
            return int(self.window.native.Handle.ToInt64())
        except Exception:
            from src.core.desktop import user32
            return user32.FindWindowW(None, "WordPulse") or 0

    def _monitor_rect(self):
        return system.monitor_rect(self.settings.monitor)

    @staticmethod
    def _dpi_scale() -> float:
        try:
            import ctypes
            return ctypes.windll.user32.GetDpiForSystem() / 96.0
        except Exception:
            return 1.0

    def _reposition(self):
        """Moves the lyrics to the chosen monitor in whatever mode we're in."""
        if not (self.window and HAS_WEBVIEW):
            return
        mode = self.settings.display_mode
        try:
            if mode == DisplayMode.DESKTOP_WALLPAPER:
                self.pinner.attach(self._window_hwnd(), self._monitor_rect())
                return
            x, y, w, h = self._monitor_rect()
            k = self._dpi_scale()
            was_full = bool(self.window.fullscreen)
            if was_full:
                self.window.toggle_fullscreen()
            if mode == DisplayMode.FULLSCREEN_AMBIENT:
                self.window.move(int(x / k) + 40, int(y / k) + 40)
                self.window.toggle_fullscreen()
            else:
                self.window.move(int((x + w / 2) / k) - 500, int((y + h / 2) / k) - 260)
        except Exception:
            log.exception("Moving to monitor failed")

    def set_display_mode(self, mode: DisplayMode):
        self.settings.display_mode = mode
        self.push()
        self.save()
        if not (self.window and HAS_WEBVIEW):
            return
        try:
            if mode == DisplayMode.DESKTOP_WALLPAPER:
                if self.window.fullscreen:
                    self.window.toggle_fullscreen()
                self.pinner.attach(self._window_hwnd(), self._monitor_rect())
                self._sync_extra_windows()
                return
            if self.pinner.attached:
                self.pinner.detach()
            self._sync_extra_windows()
            want_fullscreen = (mode == DisplayMode.FULLSCREEN_AMBIENT)
            if not want_fullscreen:
                if self.window.fullscreen:
                    self.window.toggle_fullscreen()
                self.window.resize(1000, 520)
            self._reposition()
            self.window.on_top = self.settings.always_on_top
        except Exception:
            log.exception("Display mode switch failed")

    def toggle_mock_mode(self, is_mock: bool):
        self.settings.mock_mode = is_mock
        self.push()
        self.current_track = None  # Force refresh

    def seek(self, position_sec: float):
        if self.settings.mock_mode:
            self.mock_provider.seek(position_sec)

    def toggle_playback(self):
        if self.settings.mock_mode:
            self.mock_provider.toggle_playback()

    def next_track(self):
        if self.settings.mock_mode:
            self.mock_provider.next_track()

    def prev_track(self):
        if self.settings.mock_mode:
            self.mock_provider.prev_track()

    # ------------------------------------------------------------------ timing
    def set_timing_offset(self, offset_ms: int):
        self.settings.timing_offset_ms = int(offset_ms)
        self.push()
        self.save()

    def adjust_timing_offset(self, delta_ms: int):
        self.set_timing_offset(self.settings.timing_offset_ms + int(delta_ms))

    def adjust_song_offset(self, delta_ms: int):
        """Nudges timing for the song that's playing; remembered for next time."""
        t = self.current_track
        if not t:
            return self.adjust_timing_offset(delta_ms)
        current = self.runtime["song_offset_ms"]
        new = current + int(delta_ms)
        if self.config:
            new = self.config.set_song_offset(t.title, t.artist, new)
        self.runtime["song_offset_ms"] = new
        self.push()
        return new

    def reset_song_offset(self):
        t = self.current_track
        if t and self.config:
            self.config.set_song_offset(t.title, t.artist, 0)
        self.runtime["song_offset_ms"] = 0
        self.push()
        return 0

    # ------------------------------------------------------------------ lyrics actions
    def _snapshot(self):
        if self.current_track and self.current_doc:
            self.bridge.update_snapshot(self.current_track, self.current_doc,
                                        self.current_palette or PaletteTheme.default_theme(), self.settings)
            self.push()
            self._emit_status()

    def save_tapped_timings(self, lines: list) -> bool:
        from src.lyrics.tapsync import build_enhanced_lrc, tapped_count
        track = self.current_track
        if not track or not lines or tapped_count(lines) == 0:
            return False
        doc = self.lyrics_service.save_tapped_lrc(track.title, track.artist, build_enhanced_lrc(lines))
        if doc:
            self.current_doc = doc
            self._snapshot()
        return bool(doc)

    def reset_tapped_timings(self) -> bool:
        track = self.current_track
        if not track:
            return False
        self.lyrics_service.delete_tapped(track.title, track.artist)
        self.current_doc = self.lyrics_service.get_lyrics(track.title, track.artist, track.duration)
        self._snapshot()
        return True

    def search_lyrics(self, query: str = "") -> list:
        t = self.current_track
        if not t and not query:
            return []
        return self.lyrics_service.search_alternatives(t.title if t else "", t.artist if t else "", query)

    def use_lyrics(self, lrclib_id: int) -> bool:
        t = self.current_track
        if not t:
            return False
        doc = self.lyrics_service.use_alternative(t.title, t.artist, lrclib_id)
        if doc:
            self.current_doc = doc
            self._snapshot()
        return bool(doc)

    def import_lyrics(self, text: str) -> bool:
        t = self.current_track
        if not t:
            return False
        doc = self.lyrics_service.import_lyrics(t.title, t.artist, text)
        if doc:
            self.current_doc = doc
            self._snapshot()
        return bool(doc)

    # ------------------------------------------------------------------ windows
    def _ui(self, name: str) -> str:
        return (UI_DIR / name).resolve().as_uri()

    def open_sync_window(self):
        """Opens the tap-to-sync window for the song that's playing."""
        if not HAS_WEBVIEW:
            return
        if self._sync_window is not None:
            try:
                self._sync_window.show()
                self._sync_window.restore()
                return
            except Exception:
                self._sync_window = None
        self._sync_window = webview.create_window(
            "WordPulse — Sync words", self._ui("sync.html"), js_api=self.bridge,
            width=980, height=600, min_size=(720, 460), background_color="#0b0b0d", on_top=True,
        )
        self._sync_window.events.closed += lambda: setattr(self, "_sync_window", None)

    def open_settings_window(self):
        """Small settings window; closing it just goes back to the tray."""
        if not HAS_WEBVIEW:
            return
        if self.settings_window is not None:
            try:
                self.settings_window.show()
                self.settings_window.restore()
                return
            except Exception:
                self.settings_window = None
        self.settings_window = webview.create_window(
            "WordPulse Settings", self._ui("settings.html"), js_api=self.bridge,
            width=880, height=680, min_size=(640, 520), background_color="#0e0e11",
        )
        self.settings_window.events.closed += lambda: setattr(self, "settings_window", None)

    def open_welcome_window(self):
        """First run only: what the app is and where to find it."""
        if not HAS_WEBVIEW:
            return
        self.welcome_window = webview.create_window(
            "Welcome to WordPulse", self._ui("welcome.html"), js_api=self.bridge,
            width=660, height=700, resizable=False, background_color="#0e0e11", on_top=True,
        )

    def welcome_action(self, name: str):
        if name == "settings":
            self.open_settings_window()
        elif name == "demo":
            self.toggle_mock_mode(True)
        self.settings.welcomed = True
        self.save()
        w = getattr(self, "welcome_window", None)
        if w is not None:
            try:
                w.destroy()
            except Exception:
                pass
            self.welcome_window = None
        return True

    def _daily_update_check(self):
        """At most once a day, when enabled: a tray notification if a newer release is out."""
        if not self.settings.check_updates or time.time() - self.settings.last_update_check < 86400:
            return
        self.settings.last_update_check = time.time()
        self.save()
        result = self.check_updates()
        if result.get("available") and self.on_notify:
            self.on_notify("WordPulse update available", f"Version {result['latest']} is out. Tray › Check for Updates.")

    def close_settings_window(self):
        if self.settings_window is not None:
            try:
                self.settings_window.destroy()
            except Exception:
                pass
            self.settings_window = None
        return True

    # ------------------------------------------------------------------ all displays
    def _extra_monitor_rects(self) -> list:
        """Monitors other than the main one, when "All displays" is on in desktop mode."""
        if self.settings.monitor != -1 or self.settings.display_mode != DisplayMode.DESKTOP_WALLPAPER or self.screensaver:
            return []
        mons = system.list_monitors()
        return [(m["x"], m["y"], m["w"], m["h"]) for m in mons[1:]]

    def _sync_extra_windows(self):
        """One extra lyrics window per extra monitor, each pinned behind that monitor's icons."""
        if not (HAS_WEBVIEW and self.window):
            return
        wanted = self._extra_monitor_rects()
        while len(self.extra_windows) > len(wanted):      # close ones we no longer need
            win, pin = self.extra_windows.pop()
            try:
                pin.detach()
                win.destroy()
            except Exception:
                pass
        for i, rect in enumerate(wanted):
            if i < len(self.extra_windows):
                win, pin = self.extra_windows[i]
                try:
                    pin.attach(pin.hwnd, rect)
                except Exception:
                    log.exception("Re-pinning extra display failed")
                continue
            title = f"WordPulse {i + 2}"
            win = webview.create_window(title, self._ui("index.html"), js_api=self.bridge, frameless=True,
                                        x=rect[0], y=rect[1], width=800, height=600, background_color="#000000")
            pin = DesktopPinner()

            def _shown(w=win, p=pin, r=rect, t=title):
                from src.core.desktop import user32
                hwnd = 0
                try:
                    hwnd = int(w.native.Handle.ToInt64())
                except Exception:
                    hwnd = user32.FindWindowW(None, t) or 0
                if not p.attach(hwnd, r):
                    log.warning("Could not pin lyrics to display at %s", r)
            win.events.shown += _shown
            self.extra_windows.append((win, pin))

    def open_logs(self):
        if self.log_dir and sys.platform == "win32":
            os.startfile(str(self.log_dir))
        return str(self.log_dir or "")

    def check_updates(self, notify: bool = False):
        from src.core.updates import check_for_update
        result = check_for_update(self.settings.update_repo, APP_VERSION)
        if notify and self.on_notify:
            if result.get("error"):
                self.on_notify("Update check", result["error"])
            elif result.get("available"):
                self.on_notify("Update available", f"Version {result['latest']} is out.")
            else:
                self.on_notify("Up to date", f"You have the latest version ({APP_VERSION}).")
        return result

    def settings_payload(self) -> dict:
        """Everything the settings window shows."""
        t, doc = self.current_track, self.current_doc
        source = getattr(doc, "source", "") if doc else ""
        try:
            self.settings.start_with_windows = autostart.is_enabled()
        except Exception:
            pass
        return {
            "settings": settings_to_dict(self.settings),
            "runtime": dict(self.runtime, dnd=self.dnd),
            "meta": {
                "version": APP_VERSION,
                "styles": [{"id": k, "label": v} for k, v in STYLE_LABELS.items()],
                "monitors": [m["label"] for m in system.list_monitors()],
                "players": self.known_players,
                "fonts": FONTS,
                "moods": [{"id": m, "label": MOOD_LABELS[m]} for m in MOODS],
                "song_mood": (self.config.get_song_mood(t.title, t.artist) if (self.config and t) else ""),
                "audio_device": self.audio.device_name,
                "beat": self._beat_snapshot(),
                "hotkeys": [label for label, _m, _v in system.DEFAULT_HOTKEYS.values()],
                "hotkeys_failed": self.hotkeys.failed if self.hotkeys else [],
                "log_dir": str(self.log_dir or ""),
                "save_failed": bool(self.config and getattr(self.config, "save_failed", False)),
                "track": {"title": t.title, "artist": t.artist} if t else None,
                "lyrics": {
                    "source": source,
                    "word_sync": bool(doc and doc.has_word_sync),
                    "synced": bool(doc and doc.is_synced),
                    "lines": len(doc.lines) if doc else 0,
                },
            },
        }

    def _retry_if_offline(self, now: float):
        """Lyrics failed because we were offline: try again every 45 s until they load."""
        doc, t = self.current_doc, self.current_track
        if not (doc and t and getattr(doc, "source", "") == "Offline") or now - getattr(self, "_offline_retry", 0) < 45:
            return
        self._offline_retry = now
        tid = t.track_id

        def _again():
            new = self.lyrics_service.get_lyrics(t.title, t.artist, t.duration)
            if getattr(new, "source", "") != "Offline" and self.current_track and self.current_track.track_id == tid:
                log.info("Back online: lyrics loaded for %s", t.title)
                self.current_doc = new
                self._snapshot()
        threading.Thread(target=_again, daemon=True).start()

    # ------------------------------------------------------------------ mood
    def _beat_snapshot(self) -> dict:
        fake = os.environ.get("WORDPULSE_FAKE_BPM")      # developer switch: test beat effects without audio
        if fake:
            period = 60.0 / float(fake)
            now = time.monotonic()
            return {"bpm": float(fake), "confidence": 0.9, "beat_age": now % period, "period": period,
                    "energy": 0.7, "harshness": 0.1, "brightness": 0.3, "drop_age": None,
                    "status": "listening", "listened_s": 30.0}
        return self.audio.snapshot()

    def _start_mood(self, track: TrackInfo):
        """New song: forget the old tempo and look the artist up in the background."""
        self.audio.reset()
        self._mood_started = time.time()
        self._tags = self.genre.get(track.artist) or []
        override = self.config.get_song_mood(track.title, track.artist) if self.config else ""
        self.runtime.update(mood=override, mood_source="you" if override else "", mood_reason="",
                            mood_bpm=0)
        self.push()
        if not self._tags and not self.settings.mock_mode:
            artist = track.artist

            def _fetch():
                tags = self.genre.fetch(artist)
                if self.current_track and self.current_track.artist == artist:
                    self._tags = tags
            threading.Thread(target=_fetch, daemon=True).start()

    def _mood_tick(self, track: Optional[TrackInfo]):
        """Once a second: run capture only while music plays; settle on a mood ~10 s into a song."""
        playing = bool(track and track.status == PlaybackStatus.PLAYING)
        want_audio = (playing and self.settings.auto_mood != "off" and not self.settings.mock_mode
                      and not self.runtime["hidden"])
        self.audio.active = want_audio
        status = self.audio.status if self.audio.available else "unavailable"
        if status != self.runtime["audio"]:
            self.runtime["audio"] = status
            self.push()
        if not track or self.settings.auto_mood == "off" or self.runtime["mood_source"] in ("you", "auto"):
            return
        beat = self.audio.snapshot()
        listened = beat.get("listened_s", 0)
        lyrics_ready = bool(self.current_doc and getattr(self.current_doc, "source", "") not in ("Loading",))
        elapsed = time.time() - self._mood_started
        audio_ok = self.audio.available and not self.settings.mock_mode and status == "listening"
        ready = (audio_ok and listened >= 10 and (beat["confidence"] >= 0.2 or listened >= 20)) or \
                (not audio_ok and lyrics_ready and elapsed >= 3) or elapsed >= 30
        if not ready:
            return
        mood, eff, reason = classify(beat["bpm"], beat["confidence"], beat["energy"], beat["harshness"],
                                     word_rate(self.current_doc), self._tags)
        self.runtime.update(mood=mood, mood_bpm=round(eff), mood_reason=reason, mood_source="auto")
        log.info("Mood for %s: %s (%s)", track.title, mood, reason)
        self.push()
        self._emit_status()

    def set_song_mood(self, mood: str):
        """Your choice of mood for the song that's playing ("" = automatic)."""
        mood = (mood or "").upper()
        if mood and mood not in MOODS:
            raise ValueError("mood")
        t = self.current_track
        if t and self.config:
            self.config.set_song_mood(t.title, t.artist, mood)
        if mood:
            self.runtime.update(mood=mood, mood_source="you")
        else:
            self.runtime.update(mood="", mood_source="", mood_reason="")
            self._mood_started = time.time() - 10        # re-decide straight away
        self.push()
        return self.settings_payload()

    # ------------------------------------------------------------------ hotkeys
    def _start_hotkeys(self):
        if self.hotkeys or self.screensaver:
            return
        self.hotkeys = system.HotkeyListener({
            "toggle": self.toggle_dnd,
            "next_style": self.next_style,
            "settings": self.open_settings_window,
            "earlier": lambda: self.adjust_song_offset(-100),
            "later": lambda: self.adjust_song_offset(100),
        })
        self.hotkeys.start()

    def _stop_hotkeys(self):
        if self.hotkeys:
            self.hotkeys.stop()
            self.hotkeys = None

    # ------------------------------------------------------------------ status / hiding
    def _emit_status(self):
        if not self.on_status:
            return
        t, doc = self.current_track, self.current_doc
        if not t:
            self.on_status("WordPulse — waiting for music")
            return
        src = getattr(doc, "source", "") if doc else ""
        kind = ("your taps" if src == "Tapped" else "loading…" if src == "Loading" else "offline" if src == "Offline"
                else "not found" if src == "None" else "word timing" if doc and doc.has_word_sync
                else "estimated timing" if doc and doc.is_synced else "no timing")
        text = f"{t.title} — {t.artist}"
        mood = self.runtime.get("mood")
        extra = f" · {MOOD_LABELS.get(mood, mood)}" + (f" {self.runtime['mood_bpm']} BPM" if self.runtime.get("mood_bpm") else "") if mood else ""
        self.on_status(f"WordPulse\n{text[:70]}\nLyrics: {kind}{extra}")

    def _update_hidden(self, track: Optional[TrackInfo] = None):
        s, now = self.settings, time.time()
        playing = bool(track and track.status == PlaybackStatus.PLAYING) if track is not None else (self._paused_since is None)
        if track is not None:
            self._paused_since = None if playing else (self._paused_since or now)
        hidden = self.dnd
        if s.hide_on_fullscreen and s.display_mode != DisplayMode.FULLSCREEN_AMBIENT and not self.screensaver \
                and system.fullscreen_app_running():
            hidden = True
        if s.hide_when_paused_s and self._paused_since and now - self._paused_since > s.hide_when_paused_s:
            hidden = True
        if hidden != self.runtime["hidden"]:
            self.runtime["hidden"] = hidden
            self.push()

    def _refresh_palette(self):
        t = self.current_track
        if self.settings.auto_theme and t and t.thumbnail_base64:
            self.current_palette = self.palette_extractor.extract_from_base64(t.thumbnail_base64)
        else:
            self.current_palette = PaletteTheme.default_theme()
        self._snapshot()

    # ------------------------------------------------------------------ media loop
    async def tick_media_update(self) -> Optional[TrackInfo]:
        """Polls current media state, checks for track changes, and updates UI."""
        provider = self.media_provider
        track = await provider.get_current_track()

        if not track:
            if self.power_manager.is_inhibited:
                self.power_manager.prevent_sleep(False)
            return None

        if self.settings.keep_awake and track.status == PlaybackStatus.PLAYING:
            if not self.power_manager.is_inhibited:
                self.power_manager.prevent_sleep(True)
        elif self.power_manager.is_inhibited:
            self.power_manager.prevent_sleep(False)

        is_new_track = (
            self.current_track is None or
            self.current_track.title != track.title or
            self.current_track.artist != track.artist
        )

        if is_new_track:
            self.current_track = track
            expected_id = track.track_id
            self.runtime["song_offset_ms"] = self.config.get_song_offset(track.title, track.artist) if self.config else 0
            self._start_mood(track)

            if self.settings.auto_theme and track.thumbnail_base64:
                self.current_palette = self.palette_extractor.extract_from_base64(track.thumbnail_base64)
            else:
                self.current_palette = PaletteTheme.default_theme()

            cached_doc = self.lyrics_service.get_cached_lyrics(track.title, track.artist)
            if cached_doc:
                self.current_doc = cached_doc
                self._snapshot()
            else:
                placeholder_line = LyricLine(text="", start_time=0.0, end_time=999.0,
                                             words=[LyricWord(text="…", start_time=0.0, end_time=999.0)])
                self.current_doc = LyricsDocument(track_title=track.title, artist=track.artist,
                                                  lines=[placeholder_line], is_synced=False,
                                                  has_word_sync=False, source="Loading")
                self._snapshot()

                def _bg_fetch(title=track.title, artist=track.artist, dur=track.duration, tid=expected_id):
                    try:
                        doc = self.lyrics_service.get_lyrics(title, artist, dur)
                    except Exception:
                        log.exception("Lyrics fetch failed")
                        return
                    if self.current_track and self.current_track.track_id == tid:
                        self.current_doc = doc
                        self._snapshot()

                threading.Thread(target=_bg_fetch, daemon=True).start()
        else:
            self.bridge.update_playback_position(track.position, track.status.value, track.track_id)

        return track

    def _polling_worker(self):
        """Background thread: media every 0.25s, housekeeping less often."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        last_slow = last_battery = 0.0
        while self.is_running:
            track = None
            try:
                track = loop.run_until_complete(self.tick_media_update())
            except Exception:
                log.exception("Media poll failed")
            now = time.time()
            if now - last_slow > 1.0:
                last_slow = now
                try:
                    self._update_hidden(track)
                    self._mood_tick(track)
                    self._retry_if_offline(now)
                    if self.settings.display_mode == DisplayMode.DESKTOP_WALLPAPER and not self.pinner.is_healthy():
                        log.warning("Desktop host changed (Explorer restarted?); reattaching")
                        self.pinner.reattach()
                    # the app list only feeds the settings window; refresh it every 10 s
                    if not self.settings.mock_mode and (now - self._players_at > 10 or self.settings_window is not None and now - self._players_at > 2):
                        self._players_at = now
                        self.known_players = loop.run_until_complete(self.gsmtc_provider.list_players())
                except Exception:
                    log.exception("Housekeeping failed")
            if now - last_battery > 30:
                last_battery = now
                batt = system.on_battery()
                if batt != self.runtime["on_battery"]:
                    self.runtime["on_battery"] = batt
                    self.push()
            # poll quickly while music plays; relax while paused or nothing is open
            time.sleep(0.25 if (track and track.status == PlaybackStatus.PLAYING) else 0.6)
        loop.close()

    def start(self):
        if not self.is_running:
            self.is_running = True
            self._poll_thread = threading.Thread(target=self._polling_worker, daemon=True)
            self._poll_thread.start()
            if self.settings.hotkeys_enabled:
                self._start_hotkeys()
            self.audio.start()
            threading.Thread(target=self.lyrics_service.prune_cache, daemon=True).start()
            if not self.screensaver:
                threading.Timer(20, self._daily_update_check).start()

    def stop(self):
        self.is_running = False
        self._stop_hotkeys()
        self.audio.stop()
        if self.power_manager.is_inhibited:
            self.power_manager.prevent_sleep(False)

    def quit(self):
        self.stop()
        if self.config:
            try:
                self.config.save(self.settings)
            except Exception:
                log.exception("Saving settings on exit failed")
        try:
            self.pinner.detach()
            for win, pin in self.extra_windows:
                pin.detach()
        except Exception:
            pass
        for w in [self.settings_window, self._sync_window, self.window] + [win for win, _ in self.extra_windows]:
            if w is not None:
                try:
                    w.destroy()
                except Exception:
                    pass
        os._exit(0)

    def launch_window(self):
        """Launches the WebView2 window and starts application."""
        if not HAS_WEBVIEW:
            print("pywebview is required to launch the UI window.")
            return

        mode = self.settings.display_mode
        is_fullscreen = (mode == DisplayMode.FULLSCREEN_AMBIENT)
        on_desktop = (mode == DisplayMode.DESKTOP_WALLPAPER)
        screen_w, screen_h = primary_screen_size()
        if on_desktop:
            size = dict(width=screen_w, height=screen_h, x=0, y=0)
        elif is_fullscreen:
            size = dict(width=1280, height=720)
        else:
            size = dict(width=1000, height=520)
        self.window = webview.create_window(
            title="WordPulse",
            url=self._ui("index.html"),
            js_api=self.bridge,
            fullscreen=is_fullscreen,
            on_top=self.screensaver or (self.settings.always_on_top and not on_desktop),  # screensaver covers the taskbar
            frameless=True,
            easy_drag=not on_desktop,
            resizable=True,
            # see-through only for the floating window; it costs smoothness elsewhere
            transparent=(mode == DisplayMode.DESKTOP_OVERLAY),
            background_color="#000000",
            **size,
        )

        def _on_shown():
            if self.settings.display_mode == DisplayMode.DESKTOP_WALLPAPER:
                if not self.pinner.attach(self._window_hwnd(), self._monitor_rect()):
                    log.warning("Could not attach to the desktop; falling back to a fullscreen window.")
                    self.set_display_mode(DisplayMode.FULLSCREEN_AMBIENT)
                else:
                    self._sync_extra_windows()
            elif self.settings.display_mode == DisplayMode.FULLSCREEN_AMBIENT:
                # pywebview's fullscreen stops at the taskbar; cover the whole monitor ourselves
                from src.core.desktop import cover_monitor
                cover_monitor(self._window_hwnd(), self._monitor_rect(), topmost=self.screensaver)
            elif self.settings.monitor:
                self._reposition()

        self.window.events.shown += _on_shown
        self.window.events.closed += lambda: self.pinner.detach()
        self.bridge.set_window(self.window)

        self.start()
        webview.start(debug=False)
