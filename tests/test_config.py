import json
import time

import pytest

from src.core.app import AppCoordinator
from src.core.config import ConfigStore, coerce
from src.models.settings import AppSettings, DisplayMode, DisplayStyle


def test_settings_round_trip(tmp_path):
    store = ConfigStore(tmp_path)
    s = AppSettings(display_style=DisplayStyle.REMOLD, position="top-left", font_scale=1.3,
                    auto_theme=False, highlight_color="#12abef", shuffle="line",
                    shuffle_pool=["POP", "REMOLD"], mock_mode=True)
    store.save(s)
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["display_style"] == "REMOLD"
    assert "mock_mode" not in saved                     # runtime-only fields are never written

    loaded = store.load()
    assert loaded.display_style == DisplayStyle.REMOLD
    assert loaded.position == "top-left"
    assert loaded.font_scale == 1.3
    assert loaded.highlight_color == "#12abef"
    assert loaded.shuffle_pool == ["POP", "REMOLD"]
    assert loaded.mock_mode is False


def test_broken_or_unknown_values_keep_defaults(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({
        "display_style": "NOT_A_STYLE", "font_scale": 99, "highlight_color": "pink", "no_such_key": 1,
    }))
    s = ConfigStore(tmp_path).load()
    assert s.display_style == DisplayStyle.SHIP
    assert s.font_scale == 1.8                          # clamped, not rejected
    assert s.highlight_color == "#ff2d6f"


def test_coerce_validates():
    assert coerce("display_mode", "fullscreen_ambient", DisplayMode.DESKTOP_WALLPAPER) == DisplayMode.FULLSCREEN_AMBIENT
    assert coerce("max_width_pct", 500, 78) == 95
    with pytest.raises(ValueError):
        coerce("position", "middle-ish", "center")
    with pytest.raises(ValueError):
        coerce("shuffle_pool", [], [])


def test_song_offsets_persist(tmp_path):
    store = ConfigStore(tmp_path)
    assert store.set_song_offset("Neon Tide", "Low Harbor", 250) == 250
    assert ConfigStore(tmp_path).get_song_offset("Neon Tide", "Low Harbor") == 250
    store.set_song_offset("Neon Tide", "Low Harbor", 0)
    assert ConfigStore(tmp_path).get_song_offset("Neon Tide", "Low Harbor") == 0


def test_coordinator_set_setting_saves_and_publishes(tmp_path):
    store = ConfigStore(tmp_path)
    c = AppCoordinator(settings=AppSettings(mock_mode=True), config=store)
    payload = c.set_setting("slab_shape", "pill")
    assert payload["settings"]["slab_shape"] == "pill"
    assert c.bridge.get_state()["settings"]["slab_shape"] == "pill"     # the page sees it
    c.set_setting("display_style", "ORBIT")
    store.save(c.settings)                                              # flush the debounced save
    assert ConfigStore(tmp_path).load().display_style == DisplayStyle.ORBIT
    with pytest.raises(ValueError):
        c.set_setting("no_such_setting", 1)


def test_per_song_offset_follows_the_track(tmp_path):
    import asyncio
    store = ConfigStore(tmp_path)
    c = AppCoordinator(settings=AppSettings(mock_mode=True), config=store)
    asyncio.run(c.tick_media_update())
    assert c.adjust_song_offset(200) == 200
    assert c.bridge.get_state()["settings"]["song_offset_ms"] == 200
    # a fresh coordinator picks the saved offset up again for the same song
    c2 = AppCoordinator(settings=AppSettings(mock_mode=True), config=ConfigStore(tmp_path))
    asyncio.run(c2.tick_media_update())
    assert c2.runtime["song_offset_ms"] == 200


def test_settings_payload_has_what_the_window_needs():
    c = AppCoordinator(settings=AppSettings(mock_mode=True))
    p = c.settings_payload()
    assert {"settings", "runtime", "meta"} <= set(p)
    assert len(p["meta"]["styles"]) == len(DisplayStyle)
    assert p["meta"]["monitors"]


def test_mood_settings_validate_and_persist(tmp_path):
    store = ConfigStore(tmp_path)
    c = AppCoordinator(settings=AppSettings(mock_mode=True), config=store)
    p = c.set_setting("mood_styles", {"NEON": "pop", "BOGUS": "SHIP", "SOFT": ["line", "LINE", "orbit"], "HEAVY": []})
    assert p["settings"]["mood_styles"]["NEON"] == ["POP"]
    assert p["settings"]["mood_styles"]["SOFT"] == ["LINE", "ORBIT"]          # de-duplicated
    assert p["settings"]["mood_styles"]["HEAVY"] == ["STAMP", "SQUEEZE", "SHIP", "CODE"]   # empty -> default pool
    with pytest.raises(ValueError):
        c.set_setting("variety", "chaotic")
    assert c.set_setting("variety", "lively")["settings"]["variety"] == "lively"
    assert "BOGUS" not in p["settings"]["mood_styles"]
    with pytest.raises(ValueError):
        c.set_setting("auto_mood", "sometimes")
    c.set_setting("auto_mood", "beats")
    store.save(c.settings)
    assert ConfigStore(tmp_path).load().auto_mood == "beats"


def test_song_mood_override_is_remembered(tmp_path):
    import asyncio
    store = ConfigStore(tmp_path)
    c = AppCoordinator(settings=AppSettings(mock_mode=True), config=store)
    asyncio.run(c.tick_media_update())
    c.set_song_mood("HEAVY")
    assert c.runtime["mood"] == "HEAVY" and c.runtime["mood_source"] == "you"
    c2 = AppCoordinator(settings=AppSettings(mock_mode=True), config=ConfigStore(tmp_path))
    asyncio.run(c2.tick_media_update())
    assert c2.runtime["mood"] == "HEAVY"
    with pytest.raises(ValueError):
        c.set_song_mood("SPOOKY")


def test_demo_song_gets_a_mood_from_lyrics_alone(tmp_path):
    import asyncio, time as _t
    c = AppCoordinator(settings=AppSettings(mock_mode=True), config=ConfigStore(tmp_path))
    asyncio.run(c.tick_media_update())
    c._mood_started = _t.time() - 5            # pretend a few seconds have passed
    c._mood_tick(c.current_track)
    assert c.runtime["mood"] in ("NEON", "BRIGHT", "HEAVY", "SMOOTH", "SOFT")
    assert c.runtime["mood_source"] == "auto"
    assert c.audio.active is False             # demo mode never listens to the speakers


def test_fullscreen_layout_setting(tmp_path):
    c = AppCoordinator(settings=AppSettings(mock_mode=True), config=ConfigStore(tmp_path))
    assert c.set_setting("fullscreen_layout", "art")["settings"]["fullscreen_layout"] == "art"
    with pytest.raises(ValueError):
        c.set_setting("fullscreen_layout", "cinema")


def test_real_player_controls_are_queued_for_the_media_thread():
    c = AppCoordinator(settings=AppSettings(mock_mode=False))
    c.toggle_playback(); c.next_track(); c.prev_track()
    got = [c._commands.get_nowait() for _ in range(3)]
    assert got == ["play_pause", "next", "previous"]
