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
        return "[00:01.00] <00:01.00> Lantern <00:01.60> in <00:01.90> the <00:02.20> rain"

    monkeypatch.setattr(service, "_fetch_from_lrclib", fake_fetch)

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
