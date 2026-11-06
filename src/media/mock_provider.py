"""Mock media provider for offline testing, demos, and headless development."""
import time
from typing import Callable, List, Optional
from src.media.base import BaseMediaProvider
from src.models.track import PlaybackStatus, TrackInfo
from src.lyrics.builtin_lyrics import DEMO_TRACKS
from src.media.demo_art import demo_cover


class MockMediaProvider(BaseMediaProvider):
    """Simulates real-time media player sessions with built-in tracks."""

    DEFAULT_TRACKS = DEMO_TRACKS

    def __init__(self, tracks: Optional[List[dict]] = None):
        self.tracks = tracks or self.DEFAULT_TRACKS
        self.current_index = 0
        self.status = PlaybackStatus.PLAYING
        self.position = 0.0
        self.last_update_time = time.time()
        self._on_track_change: Optional[Callable[[TrackInfo], None]] = None

    def set_on_track_change(self, callback: Callable[[TrackInfo], None]) -> None:
        self._on_track_change = callback

    def _get_extrapolated_position(self) -> float:
        now = time.time()
        if self.status == PlaybackStatus.PLAYING:
            elapsed = now - self.last_update_time
            curr = self.position + elapsed
            dur = self.tracks[self.current_index]["duration"]
            if curr >= dur:
                self.next_track()
                return 0.0
            return curr
        return self.position

    async def get_current_track(self) -> Optional[TrackInfo]:
        track_data = self.tracks[self.current_index]
        current_pos = self._get_extrapolated_position()
        
        return TrackInfo(
            title=track_data["title"],
            artist=track_data["artist"],
            album=track_data["album"],
            duration=track_data["duration"],
            position=round(current_pos, 3),
            status=self.status,
            app_name=track_data["app_name"],
            thumbnail_base64=demo_cover(track_data["title"])
        )

    def play(self) -> None:
        if self.status != PlaybackStatus.PLAYING:
            self.last_update_time = time.time()
            self.status = PlaybackStatus.PLAYING

    def pause(self) -> None:
        if self.status == PlaybackStatus.PLAYING:
            self.position = self._get_extrapolated_position()
            self.last_update_time = time.time()
            self.status = PlaybackStatus.PAUSED

    def toggle_playback(self) -> None:
        if self.status == PlaybackStatus.PLAYING:
            self.pause()
        else:
            self.play()

    def seek(self, new_position: float) -> None:
        self.position = max(0.0, min(new_position, self.tracks[self.current_index]["duration"]))
        self.last_update_time = time.time()

    def next_track(self) -> None:
        self.current_index = (self.current_index + 1) % len(self.tracks)
        self.position = 0.0
        self.last_update_time = time.time()
        if self._on_track_change:
            track_data = self.tracks[self.current_index]
            self._on_track_change(TrackInfo(
                title=track_data["title"],
                artist=track_data["artist"],
                album=track_data["album"],
                duration=track_data["duration"],
                position=0.0,
                status=self.status,
                app_name=track_data["app_name"]
            ))

    def prev_track(self) -> None:
        self.current_index = (self.current_index - 1) % len(self.tracks)
        self.position = 0.0
        self.last_update_time = time.time()
        if self._on_track_change:
            track_data = self.tracks[self.current_index]
            self._on_track_change(TrackInfo(
                title=track_data["title"],
                artist=track_data["artist"],
                album=track_data["album"],
                duration=track_data["duration"],
                position=0.0,
                status=self.status,
                app_name=track_data["app_name"]
            ))

