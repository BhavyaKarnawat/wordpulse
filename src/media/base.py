"""Base interface for media transport session providers."""
from abc import ABC, abstractmethod
from typing import Callable, Optional
from src.models.track import TrackInfo


class BaseMediaProvider(ABC):
    """Abstract provider that delivers current media information and position."""

    @abstractmethod
    async def get_current_track(self) -> Optional[TrackInfo]:
        """Fetches the latest metadata and extrapolated playback position."""
        pass

    @abstractmethod
    def set_on_track_change(self, callback: Callable[[TrackInfo], None]) -> None:
        """Registers a listener called when the playing track changes."""
        pass

