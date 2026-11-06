import pytest
import asyncio
import time
from src.media.base import BaseMediaProvider
from src.media.mock_provider import MockMediaProvider
from src.models.track import PlaybackStatus

def test_mock_media_provider_initial_state():
    async def _test():
        provider = MockMediaProvider()
        track = await provider.get_current_track()
        
        assert track is not None
        assert track.title == "Neon Tide"
        assert track.artist == "Low Harbor"
        assert track.status == PlaybackStatus.PLAYING
        assert track.duration > 60
    
    asyncio.run(_test())

def test_mock_media_provider_playback_controls():
    async def _test():
        provider = MockMediaProvider()
        
        # Pause
        provider.pause()
        track = await provider.get_current_track()
        assert track.status == PlaybackStatus.PAUSED
        pos1 = track.position
        
        await asyncio.sleep(0.05)
        track2 = await provider.get_current_track()
        assert track2.position == pos1
        
        # Resume play
        provider.play()
        track3 = await provider.get_current_track()
        assert track3.status == PlaybackStatus.PLAYING
    
    asyncio.run(_test())

def test_mock_media_provider_track_switch():
    async def _test():
        provider = MockMediaProvider()
        provider.next_track()
        track = await provider.get_current_track()
        assert track.title == "Paper Satellites"
        assert track.artist == "The Quiet Arcade"
        assert track.position == 0.0
    
    asyncio.run(_test())

def test_mock_media_provider_extrapolation():
    async def _test():
        provider = MockMediaProvider()
        provider.seek(10.0)
        provider.play()
        
        track1 = await provider.get_current_track()
        assert pytest.approx(track1.position, 0.1) == 10.0
        
        await asyncio.sleep(0.15)
        track2 = await provider.get_current_track()
        assert track2.position > track1.position
        assert pytest.approx(track2.position, 0.1) == 10.15
    
    asyncio.run(_test())
