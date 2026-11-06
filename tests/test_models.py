import pytest
from src.models.track import TrackInfo, PlaybackStatus
from src.models.lyrics import LyricWord, LyricLine, LyricsDocument
from src.models.theme import PaletteTheme
from src.models.settings import AppSettings, DisplayStyle, DisplayMode

def test_track_info_creation():
    track = TrackInfo(
        title="Neon Tide",
        artist="Low Harbor",
        album="Harbor Lights",
        duration=354.0,
        position=12.5,
        status=PlaybackStatus.PLAYING,
        app_name="Spotify",
        thumbnail_base64="data:image/jpeg;base64,..."
    )
    assert track.title == "Neon Tide"
    assert track.artist == "Low Harbor"
    assert track.is_playing is True
    assert track.display_title == "Neon Tide"

def test_lyric_word_and_line():
    word1 = LyricWord(text="Hold", start_time=0.42, end_time=0.80, icon="❓")
    word2 = LyricWord(text="on", start_time=0.80, end_time=1.20)
    line = LyricLine(
        text="Hold on to the light?",
        start_time=0.42,
        end_time=3.50,
        words=[word1, word2]
    )
    assert len(line.words) == 2
    assert line.words[0].icon == "❓"
    assert line.contains_time(1.0) is True
    assert line.contains_time(4.0) is False

def test_lyrics_document():
    word1 = LyricWord(text="Hello", start_time=1.0, end_time=2.0)
    line1 = LyricLine(text="Hello", start_time=1.0, end_time=2.5, words=[word1])
    doc = LyricsDocument(
        track_title="Hello",
        artist="Mara Vell",
        lines=[line1],
        is_synced=True,
        has_word_sync=True
    )
    assert doc.is_synced is True
    assert doc.has_word_sync is True
    active_line, active_word = doc.get_active_indices(1.5)
    assert active_line == 0
    assert active_word == 0

def test_palette_theme_defaults():
    theme = PaletteTheme.default_theme()
    assert theme.background.startswith("#")
    assert theme.highlight.startswith("#")
    assert theme.text_primary.startswith("#")

def test_app_settings():
    settings = AppSettings()
    assert settings.display_style == DisplayStyle.SHIP
    assert settings.display_mode == DisplayMode.DESKTOP_WALLPAPER
    assert settings.keep_awake is True
    assert settings.timing_offset_ms == 0

