import pytest
import os
import shutil
from src.lyrics.service import LyricsService
from src.core.parser import LRCParser
from src.core.icon_mapper import LyricIconMapper

TEST_CACHE_DIR = "tests/test_cache"

@pytest.fixture(autouse=True)
def cleanup_cache():
    if os.path.exists(TEST_CACHE_DIR):
        shutil.rmtree(TEST_CACHE_DIR)
    yield
    if os.path.exists(TEST_CACHE_DIR):
        shutil.rmtree(TEST_CACHE_DIR)

def test_lyrics_service_mock_track():
    service = LyricsService(cache_dir=TEST_CACHE_DIR)
    doc = service.get_lyrics("Neon Tide", "Low Harbor")
    
    assert doc is not None
    assert doc.track_title == "Neon Tide"
    assert doc.is_synced is True
    assert len(doc.lines) > 0
    # Check that icons were enriched
    has_any_icon = any(w.icon is not None for line in doc.lines for w in line.words)
    assert has_any_icon is True

def test_lyrics_service_caching(monkeypatch):
    service = LyricsService(cache_dir=TEST_CACHE_DIR)
    calls = []

    def fake_fetch(title, artist, duration=0.0):
        calls.append(title)
        return "[00:01.00] <00:01.00> Lantern <00:01.60> in <00:01.90> the <00:02.20> rain", "LRCLIB"

    monkeypatch.setattr(service, "_fetch_online", fake_fetch)

    # First fetch goes to the network (stubbed) and populates the cache
    doc1 = service.get_lyrics("Unlisted Song", "Nobody In Particular")
    assert doc1.is_synced is True
    assert len(os.listdir(TEST_CACHE_DIR)) > 0

    # Second fetch is served from the cache without another network call
    doc2 = service.get_lyrics("Unlisted Song", "Nobody In Particular")
    assert len(calls) == 1
    assert doc2.track_title == doc1.track_title
    assert len(doc2.lines) == len(doc1.lines)

def test_lyrics_service_fallback_document():
    service = LyricsService(cache_dir=TEST_CACHE_DIR)
    # Unknown track with network disabled/mocked
    doc = service.create_empty_or_placeholder_doc("Random Track 123", "Unknown Artist")
    assert doc.track_title == "Random Track 123"
    assert doc.is_synced is False
    assert len(doc.lines) == 1
    assert "No synced lyrics" in doc.lines[0].text



def test_offline_is_not_mistaken_for_not_found(monkeypatch):
    import urllib.error, urllib.request
    service = LyricsService(cache_dir=TEST_CACHE_DIR)

    def no_network(*a, **k):
        raise urllib.error.URLError("no route to host")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(service, "_other_providers", lambda: [("Down", _Down())])
    doc = service.get_lyrics("Unlisted Song", "Nobody In Particular")
    assert doc.source == "Offline"
    assert not any(f.endswith(".none.json") for f in os.listdir(TEST_CACHE_DIR))   # nothing remembered


def test_not_found_is_remembered(monkeypatch):
    import io, urllib.error, urllib.request
    service = LyricsService(cache_dir=TEST_CACHE_DIR)
    calls = []

    def not_found(req, *a, **k):
        calls.append(1)
        raise urllib.error.HTTPError(getattr(req, "full_url", ""), 404, "Not Found", {}, io.BytesIO(b""))
    monkeypatch.setattr(urllib.request, "urlopen", not_found)
    monkeypatch.setattr("src.lyrics.service.HAS_SYNCEDLYRICS", False)
    first = service.get_lyrics("Unlisted Song", "Nobody In Particular")
    assert first.source != "Offline"
    n = len(calls)
    service.get_lyrics("Unlisted Song", "Nobody In Particular")
    assert len(calls) == n                       # the second play didn't touch the network


def test_prune_keeps_taps(tmp_path):
    import json
    service = LyricsService(cache_dir=str(tmp_path))
    for i in range(12):
        (tmp_path / f"song{i}.json").write_text(json.dumps({"raw_lrc": "x"}))
    (tmp_path / "mine.tapped.json").write_text(json.dumps({"raw_lrc": "x"}))
    assert service.prune_cache(max_files=5) == 7
    assert (tmp_path / "mine.tapped.json").exists()


# ---- fallback sources (all faked: no network) ----
from syncedlyrics.utils import Lyrics

SYNCED = "[00:01.00] Lantern in the rain\n[00:03.00] Second line"
PLAIN = "Lantern in the rain\nSecond line"


class _Down:
    def get_lrc(self, term):
        raise ConnectionError("unreachable")


class _Has:
    def __init__(self, synced=None, plain=None):
        self.calls = 0
        self.lrc = Lyrics(synced=synced, unsynced=plain)

    def get_lrc(self, term):
        self.calls += 1
        return self.lrc


class _Empty:
    def get_lrc(self, term):
        return None


def _svc(tmp_path, monkeypatch, lrclib, providers):
    svc = LyricsService(cache_dir=str(tmp_path))
    monkeypatch.setattr(svc, "_fetch_lrclib", lambda *a, **k: lrclib)
    monkeypatch.setattr(svc, "_other_providers", lambda: providers)
    return svc


def test_lrclib_down_falls_back_to_other_sources(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch, (None, None, False), [("Down", _Down()), ("NetEase", _Has(synced=SYNCED))])
    doc = svc.get_lyrics("Unlisted Song", "Nobody")
    assert doc.source == "NetEase" and doc.is_synced
    assert svc.get_cached_lyrics("Unlisted Song", "Nobody").source == "NetEase"   # source kept in the cache


def test_plain_lyrics_keep_the_search_going_for_synced(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch, (None, PLAIN, True),
               [("Musixmatch", _Has(plain=PLAIN)), ("Megalobiz", _Has(synced=SYNCED))])
    doc = svc.get_lyrics("Unlisted Song", "Nobody")
    assert doc.source == "Megalobiz" and doc.is_synced


def test_plain_lyrics_used_when_no_source_has_timing(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch, (None, None, True), [("Musixmatch", _Empty()), ("Genius", _Has(plain=PLAIN))])
    doc = svc.get_lyrics("Unlisted Song", "Nobody")
    assert doc.source == "Genius" and not doc.is_synced
    assert "Lantern" in doc.lines[0].text


def test_lrclib_synced_stops_the_search(tmp_path, monkeypatch):
    other = _Has(synced=SYNCED)
    svc = _svc(tmp_path, monkeypatch, (SYNCED, None, True), [("NetEase", other)])
    assert svc.get_lyrics("Unlisted Song", "Nobody").source == "LRCLIB"
    assert other.calls == 0


def test_offline_only_when_every_source_is_unreachable(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch, (None, None, False), [("A", _Down()), ("B", _Down())])
    assert svc.get_lyrics("Unlisted Song", "Nobody").source == "Offline"

    svc = _svc(tmp_path, monkeypatch, (None, None, False), [("A", _Down()), ("B", _Empty())])
    doc = svc.get_lyrics("Unlisted Song", "Nobody")
    assert doc.source == "None"
    assert not any(f.name.endswith(".none.json") for f in tmp_path.iterdir())   # a source was down: ask again later


def test_not_found_everywhere_is_remembered(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch, (None, None, True), [("A", _Empty())])
    assert svc.get_lyrics("Unlisted Song", "Nobody").source == "None"
    assert any(f.name.endswith(".none.json") for f in tmp_path.iterdir())


def test_search_skips_results_for_other_songs(tmp_path, monkeypatch):
    import io, json as _json, urllib.error, urllib.request
    results = [
        {"trackName": "Rain", "artistName": "Someone Else", "duration": 200, "syncedLyrics": "[00:01.00] wrong artist"},
        {"trackName": "Lantern", "artistName": "Low Harbor", "duration": 400, "syncedLyrics": "[00:01.00] wrong length"},
        {"trackName": "Lantern (Live)", "artistName": "Low Harbor feat. Guest", "duration": 201,
         "syncedLyrics": "[00:01.00] right one"},
    ]

    class Resp(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, *a, **k):
        if "/api/get" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))
        return Resp(_json.dumps(results).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    svc = LyricsService(cache_dir=str(tmp_path))
    synced, plain, reached = svc._fetch_lrclib("Lantern", "Low Harbor", 200)
    assert synced == "[00:01.00] right one" and reached

    results[:] = results[:2]                                   # only wrong songs: use none of them
    assert svc._fetch_lrclib("Lantern", "Low Harbor", 200) == (None, None, True)
