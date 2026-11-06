"""Failure paths: everything degrades to a message or a retry, never a crash."""
import json
import os

import pytest

from src.core import system
from src.core.app import AppCoordinator
from src.core.bridge import UIBridge
from src.core.config import ConfigStore
from src.lyrics.service import LyricsService
from src.models.settings import AppSettings


def test_failing_action_returns_an_error_instead_of_throwing():
    b = UIBridge()
    b.actions["boom"] = lambda: 1 / 0
    assert "ZeroDivisionError" in b._act("boom")["error"]


def test_bad_setting_values_become_friendly_errors():
    c = AppCoordinator(settings=AppSettings(mock_mode=True))
    assert "error" in c.bridge.set_setting("position", "nowhere")


def test_page_errors_are_logged_but_rate_limited(caplog):
    b = UIBridge()
    with caplog.at_level("WARNING", logger="wordpulse"):
        for i in range(50):
            b.report_error(f"oops {i}")
    assert sum("Page error" in r.message for r in caplog.records) == 20


def test_damaged_cache_file_is_dropped_and_refetched(tmp_path):
    svc = LyricsService(cache_dir=str(tmp_path))
    path = svc._get_cache_path(svc._normalize_key("Unlisted Song", "Nobody In Particular"))
    path.write_text("{ this is not json", encoding="utf-8")
    assert svc.get_cached_lyrics("Unlisted Song", "Nobody In Particular") is None
    assert not path.exists()


def test_lyrics_that_cannot_be_parsed_fall_back_to_a_placeholder(tmp_path, monkeypatch):
    svc = LyricsService(cache_dir=str(tmp_path))
    monkeypatch.setattr(svc, "_fetch_from_lrclib", lambda *a, **k: "[00:01.00] fine")
    monkeypatch.setattr(svc.parser, "parse", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad")))
    doc = svc.get_lyrics("Unlisted Song", "Nobody In Particular")
    assert doc is not None and doc.is_synced is False


def test_failed_settings_save_is_reported_not_raised(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path)

    def disk_full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(store, "_write", disk_full)
    assert store.save(AppSettings()) is False
    assert store.save_failed is True
    c = AppCoordinator(settings=AppSettings(mock_mode=True), config=store)
    assert c.settings_payload()["meta"]["save_failed"] is True


def test_retry_delays_grow_then_cap():
    d, seen = 0.0, []
    for _ in range(8):
        d = system.next_backoff(d)
        seen.append(d)
    assert seen[:4] == [2.0, 4.0, 8.0, 16.0]
    assert max(seen) == 30.0


def test_webview2_check_returns_a_bool():
    assert isinstance(system.webview2_installed(), bool)


def test_second_launch_signal_without_a_running_copy_is_harmless():
    # no listener has created the event in this test process
    assert system.signal_running_instance() in (True, False)
