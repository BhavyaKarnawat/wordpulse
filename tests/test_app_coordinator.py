import pytest
import asyncio
from src.core.bridge import UIBridge
from src.core.app import AppCoordinator
from src.models.settings import AppSettings, DisplayStyle, DisplayMode
from src.models.track import PlaybackStatus

def test_ui_bridge_state_and_playback():
    bridge = UIBridge()
    from src.models.track import TrackInfo, PlaybackStatus
    from src.models.lyrics import LyricsDocument, LyricLine, LyricWord
    from src.models.theme import PaletteTheme
    from src.models.settings import AppSettings

    track = TrackInfo(title="Test Song", artist="Artist", status=PlaybackStatus.PLAYING, duration=200, position=50)
    line = LyricLine(text="Hello", start_time=1.0, end_time=2.0, words=[LyricWord(text="Hello", start_time=1.0, end_time=2.0)])
    doc = LyricsDocument(track_title="Test Song", artist="Artist", lines=[line])
    theme = PaletteTheme.default_theme()
    settings = AppSettings()

    bridge.update_snapshot(track, doc, theme, settings)
    state = bridge.get_state()
    assert state["track"]["title"] == "Test Song"
    assert state["lyrics"]["track_title"] == "Test Song"
    assert state["version"] == 1

    pb = bridge.get_playback()
    assert pb["position"] == 50
    assert pb["status"] == "PLAYING"

def test_app_coordinator_initialization():
    settings = AppSettings(mock_mode=True)
    coordinator = AppCoordinator(settings=settings)
    
    assert coordinator.settings.mock_mode is True
    assert coordinator.media_provider is not None
    assert coordinator.lyrics_service is not None
    assert coordinator.palette_extractor is not None

def test_app_coordinator_cycle_mock():
    async def _test():
        settings = AppSettings(mock_mode=True)
        coordinator = AppCoordinator(settings=settings)
        
        # Test one tick of the update loop
        track = await coordinator.tick_media_update()
        assert track is not None
        assert track.title == "Neon Tide"
        assert coordinator.current_doc is not None
        assert coordinator.current_doc.track_title == "Neon Tide"
    
    asyncio.run(_test())

