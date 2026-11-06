"""Track and playback models."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PlaybackStatus(Enum):
    STOPPED = "STOPPED"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"


@dataclass
class TrackInfo:
    title: str
    artist: str
    album: str = ""
    duration: float = 0.0
    position: float = 0.0
    status: PlaybackStatus = PlaybackStatus.STOPPED
    app_name: str = ""
    thumbnail_base64: str = ""

    @property
    def is_playing(self) -> bool:
        return self.status == PlaybackStatus.PLAYING

    @property
    def display_title(self) -> str:
        return self.title.strip() or "No Track Playing"

    @property
    def display_artist(self) -> str:
        return self.artist.strip() or "Unknown Artist"

    @property
    def track_id(self) -> str:
        """Normalized unique identifier for the track."""
        clean_title = "".join(c.lower() for c in self.title if c.isalnum() or c.isspace()).strip()
        clean_artist = "".join(c.lower() for c in self.artist if c.isalnum() or c.isspace()).strip()
        return f"{clean_artist} - {clean_title}"

