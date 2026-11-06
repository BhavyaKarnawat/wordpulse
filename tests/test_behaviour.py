import time

from src.core.app import AppCoordinator
from src.models.settings import AppSettings
from src.models.track import PlaybackStatus, TrackInfo
import run_wordpulse


def _track(status):
    return TrackInfo(title="Neon Tide", artist="Low Harbor", album="", duration=70, position=1,
                     status=status, app_name="Spotify.exe")


def test_hide_when_paused_after_delay():
    c = AppCoordinator(settings=AppSettings(mock_mode=True, hide_when_paused_s=10, hide_on_fullscreen=False))
    c._update_hidden(_track(PlaybackStatus.PAUSED))
    assert c.runtime["hidden"] is False            # not yet
    c._paused_since = time.time() - 11
    c._update_hidden(_track(PlaybackStatus.PAUSED))
    assert c.runtime["hidden"] is True
    c._update_hidden(_track(PlaybackStatus.PLAYING))
    assert c.runtime["hidden"] is False            # playing again brings the lyrics back
    assert c.bridge.get_state()["settings"]["hidden"] is False


def test_do_not_disturb_toggle():
    c = AppCoordinator(settings=AppSettings(mock_mode=True, hide_on_fullscreen=False))
    c.toggle_dnd()
    assert c.runtime["hidden"] is True
    c.toggle_dnd()
    assert c.runtime["hidden"] is False


def test_screensaver_arguments():
    assert run_wordpulse.screensaver_command(["/s"]) == "run"
    assert run_wordpulse.screensaver_command(["/S"]) == "run"
    assert run_wordpulse.screensaver_command(["/c:1234"]) == "config"
    assert run_wordpulse.screensaver_command(["/p", "5678"]) == "preview"
    assert run_wordpulse.screensaver_command(["--demo"]) is None
    assert run_wordpulse.screensaver_command([]) is None


def test_player_choice_skips_browsers():
    from src.media.gsmtc_provider import GSMTCMediaProvider
    assert GSMTCMediaProvider.is_browser("MSEdge")
    assert GSMTCMediaProvider.is_browser("Chrome")
    assert not GSMTCMediaProvider.is_browser("Spotify.exe")


def test_all_displays_lists_every_extra_monitor(monkeypatch):
    from src.core import system
    from src.models.settings import DisplayMode
    two = [{"name": "A", "x": 0, "y": 0, "w": 1920, "h": 1080, "work": (0, 0, 1920, 1040), "primary": True},
           {"name": "B", "x": 1920, "y": -200, "w": 2560, "h": 1440, "work": (1920, -200, 2560, 1400), "primary": False}]
    monkeypatch.setattr(system, "list_monitors", lambda: two)
    c = AppCoordinator(settings=AppSettings(mock_mode=True, display_mode=DisplayMode.DESKTOP_WALLPAPER, monitor=-1))
    assert c._extra_monitor_rects() == [(1920, -200, 2560, 1440)]
    c.settings.monitor = 0
    assert c._extra_monitor_rects() == []                    # only with "All displays"
    c.settings.monitor = -1
    c.settings.display_mode = DisplayMode.FULLSCREEN_AMBIENT
    assert c._extra_monitor_rects() == []                    # only on the desktop
