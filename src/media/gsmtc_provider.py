"""Windows Global System Media Transport Controls (GSMTC) provider."""
import asyncio
import base64
import time
from datetime import datetime, timezone
from typing import Callable, Optional
from src.media.base import BaseMediaProvider
from src.models.track import PlaybackStatus, TrackInfo

try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as GSMTCStatus,
    )
    from winsdk.windows.storage.streams import DataReader
    HAS_WINSDK = True
except ImportError:
    HAS_WINSDK = False


class GSMTCMediaProvider(BaseMediaProvider):
    """Tracks media playback from Spotify, Apple Music, and Windows media apps."""

    def __init__(self):
        self._manager = None
        self._last_track_id = ""
        self._last_position = 0.0
        self._last_update_time = time.time()
        self._last_status = PlaybackStatus.STOPPED
        self._cached_thumbnail_b64 = ""
        self._on_track_change: Optional[Callable[[TrackInfo], None]] = None

    BROWSERS = ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "arc")

    # set by the coordinator from settings
    preferred_player: str = "auto"
    ignore_browsers: bool = False

    @classmethod
    def is_browser(cls, app_id: str) -> bool:
        a = (app_id or "").lower()
        return any(b in a for b in cls.BROWSERS)

    def _sessions(self, manager) -> list:
        try:
            sessions = manager.get_sessions()
            return [sessions.get_at(i) for i in range(sessions.size)] if sessions else []
        except Exception:
            return []

    def _pick_session(self, manager):
        """The session to follow: your chosen app if it is open, else Windows' current one."""
        sessions = self._sessions(manager)
        pref = (self.preferred_player or "auto").lower()
        if pref != "auto":
            for sess in sessions:
                if pref in (sess.source_app_user_model_id or "").lower():
                    return sess
        current = manager.get_current_session()
        candidates = ([current] if current else []) + [x for x in sessions if x is not current]
        for sess in candidates:
            if self.ignore_browsers and self.is_browser(sess.source_app_user_model_id):
                continue
            return sess
        return None

    async def list_players(self) -> list:
        """App ids that currently have a media session (for the settings window)."""
        manager = await self._ensure_manager()
        if not manager:
            return []
        seen = []
        for sess in self._sessions(manager):
            app = sess.source_app_user_model_id or ""
            if app and app not in seen:
                seen.append(app)
        return seen

    def set_on_track_change(self, callback: Callable[[TrackInfo], None]) -> None:
        self._on_track_change = callback

    async def _ensure_manager(self):
        if not HAS_WINSDK:
            return None
        if self._manager is None:
            try:
                self._manager = await asyncio.wait_for(SessionManager.request_async(), timeout=2.0)
            except Exception:
                self._manager = None
        return self._manager

    async def _read_thumbnail_base64(self, thumbnail_ref) -> str:
        """Reads stream from thumbnail reference and returns base64 data URI."""
        if not thumbnail_ref:
            return ""
        try:
            stream = await asyncio.wait_for(thumbnail_ref.open_read_async(), timeout=1.5)
            size = stream.size
            if size == 0 or size > 5_000_000:
                return ""
            reader = DataReader(stream.get_input_stream_at(0))
            await asyncio.wait_for(reader.load_async(size), timeout=1.5)
            buffer = bytearray(size)
            reader.read_bytes(buffer)
            b64_str = base64.b64encode(buffer).decode("ascii")
            return f"data:image/jpeg;base64,{b64_str}"
        except Exception:
            return ""

    async def get_current_track(self) -> Optional[TrackInfo]:
        if not HAS_WINSDK:
            return None

        manager = await self._ensure_manager()
        if not manager:
            return None

        try:
            session = self._pick_session(manager)

            if not session:
                self._last_status = PlaybackStatus.STOPPED
                return None

            # Get media metadata
            props = await asyncio.wait_for(session.try_get_media_properties_async(), timeout=1.5)
            if not props or not props.title:
                return None

            title = props.title.strip()
            artist = props.artist.strip() if props.artist else "Unknown Artist"
            album = props.album_title.strip() if props.album_title else ""
            app_id = session.source_app_user_model_id or "Media Player"

            # Parse playback state
            playback_info = session.get_playback_info()
            if playback_info:
                gsm_status = playback_info.playback_status
                if gsm_status == GSMTCStatus.PLAYING:
                    status = PlaybackStatus.PLAYING
                elif gsm_status == GSMTCStatus.PAUSED:
                    status = PlaybackStatus.PAUSED
                else:
                    status = PlaybackStatus.STOPPED
            else:
                status = PlaybackStatus.STOPPED

            # Timeline properties
            timeline = session.get_timeline_properties()
            reported_pos = 0.0
            duration = 0.0
            if timeline:
                if timeline.position:
                    reported_pos = timeline.position.total_seconds()
                if timeline.end_time:
                    duration = timeline.end_time.total_seconds()
                # Players (Spotify especially) only refresh the position every few seconds;
                # Windows stamps each report, so advance it by how old it is.
                if status == PlaybackStatus.PLAYING:
                    try:
                        stamp = timeline.last_updated_time
                        if stamp is not None:
                            if stamp.tzinfo is None:
                                stamp = stamp.replace(tzinfo=timezone.utc)
                            age = (datetime.now(timezone.utc) - stamp).total_seconds()
                            if 0 <= age < 60:
                                reported_pos += age
                    except Exception:
                        pass

            now = time.time()
            track_id = f"{artist} - {title}"

            # Check if track changed
            if track_id != self._last_track_id:
                self._last_track_id = track_id
                self._last_position = reported_pos
                self._last_update_time = now
                self._last_status = status
                # Fetch new thumbnail
                self._cached_thumbnail_b64 = await self._read_thumbnail_base64(props.thumbnail)
                
                track = TrackInfo(
                    title=title,
                    artist=artist,
                    album=album,
                    duration=duration,
                    position=reported_pos,
                    status=status,
                    app_name=app_id,
                    thumbnail_base64=self._cached_thumbnail_b64
                )
                if self._on_track_change:
                    self._on_track_change(track)
                return track

            # Re-anchor only when the corrected report disagrees with our clock (seek, buffering)
            predicted = self._last_position + (now - self._last_update_time if self._last_status == PlaybackStatus.PLAYING else 0)
            if abs(reported_pos - predicted) > 0.35:
                self._last_position = reported_pos
                self._last_update_time = now
                self._last_status = status
            elif status != self._last_status:
                self._last_position = reported_pos
                self._last_update_time = now
                self._last_status = status

            # Extrapolate smooth position if playing
            if status == PlaybackStatus.PLAYING:
                extrapolated = self._last_position + (now - self._last_update_time)
                if duration > 0:
                    extrapolated = min(extrapolated, duration)
            else:
                extrapolated = self._last_position

            return TrackInfo(
                title=title,
                artist=artist,
                album=album,
                duration=duration,
                position=round(extrapolated, 3),
                status=status,
                app_name=app_id,
                thumbnail_base64=self._cached_thumbnail_b64
            )
        except Exception:
            # Reset manager on COM / RPC disconnection so next poll reconnects cleanly
            self._manager = None
            return None

