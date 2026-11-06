import asyncio
import pytest
from src.core.app import AppCoordinator
from src.core.icon_mapper import LyricIconMapper
from src.models.settings import AppSettings, DisplayStyle, DisplayMode
from src.models.track import PlaybackStatus

def test_icon_mapper_expanded():
    mapper = LyricIconMapper()
    # Test the showcase words
    assert mapper.get_icon("telling") == "💬"
    assert mapper.get_icon("name") == "✍️"
    assert mapper.get_icon("need") == "🤍"
    assert mapper.get_icon("wait") == "⌛"
    assert mapper.get_icon("number") == "#️⃣"
    assert mapper.get_icon("minute") == "🕐"
    assert mapper.get_icon("faithful") == "💍"
    assert mapper.get_icon("swear") == "🤞"

def test_app_async_lyrics_and_smooth_polling():
    settings = AppSettings(mock_mode=True, display_style=DisplayStyle.FISHEYE_VISUAL)
    coordinator = AppCoordinator(settings=settings)

    # 1. Media tick should not block and should return mock track
    track = asyncio.run(coordinator.tick_media_update())
    assert track is not None
    assert track.title == "Neon Tide"
    assert track.artist == "Low Harbor"
    assert track.status == PlaybackStatus.PLAYING

    # 2. Bridge should have updated snapshot with word-by-word doc
    state = coordinator.bridge.get_state()
    assert state["track"]["title"] == "Neon Tide"
    assert state["lyrics"] is not None
    assert len(state["lyrics"]["lines"]) > 0

    # 3. Simulate continuous high-frequency ticks
    for _ in range(20):
        t = asyncio.run(coordinator.tick_media_update())
        assert t is not None

    # 4. Verify playback position updates continuously
    pb = coordinator.bridge.get_playback()
    assert pb["status"] == "PLAYING"
    assert pb["position"] >= 0.0

def test_app_display_mode_and_styles():
    coordinator = AppCoordinator(settings=AppSettings(mock_mode=True))
    
    for style in [DisplayStyle.SHIP, DisplayStyle.FISHEYE, DisplayStyle.FISHEYE_VISUAL, DisplayStyle.VISUAL]:
        coordinator.set_display_style(style)
        assert coordinator.settings.display_style == style

    coordinator.set_display_mode(DisplayMode.DESKTOP_OVERLAY)
    assert coordinator.settings.display_mode == DisplayMode.DESKTOP_OVERLAY

    coordinator.set_display_mode(DisplayMode.FULLSCREEN_AMBIENT)
    assert coordinator.settings.display_mode == DisplayMode.FULLSCREEN_AMBIENT

