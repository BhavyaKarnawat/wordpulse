import os
import shutil
from src.lyrics.service import LyricsService
from src.lyrics.tapsync import build_enhanced_lrc, tapped_count

CACHE = "tests/test_cache_tap"

LINES = [
    {"text": "Lanterns drift across the bay", "start_time": 1.0, "words": [
        {"text": "Lanterns", "start_time": 1.05, "tapped": True},
        {"text": "drift", "start_time": 1.62, "tapped": True},
        {"text": "across", "start_time": 1.60, "tapped": True},   # late/duplicate tap
        {"text": "the", "start_time": 2.40},
        {"text": "bay", "start_time": 2.70},
    ]},
    {"text": "Every window holds a light", "start_time": 4.0, "words": [
        {"text": "Every", "start_time": 4.1}, {"text": "window", "start_time": 4.5},
        {"text": "holds", "start_time": 5.0}, {"text": "a", "start_time": 5.3}, {"text": "light", "start_time": 5.5},
    ]},
]


def test_build_enhanced_lrc_keeps_words_in_order():
    lrc = build_enhanced_lrc(LINES)
    first = lrc.splitlines()[0]
    assert first.startswith("[00:01.00] <00:01.05> Lanterns <00:01.62> drift")
    # the out-of-order tap is nudged forward instead of going backwards
    assert "<00:01.64> across" in first
    assert tapped_count(LINES) == 3


def test_tapped_timing_saved_and_preferred():
    shutil.rmtree(CACHE, ignore_errors=True)
    try:
        svc = LyricsService(cache_dir=CACHE)
        doc = svc.save_tapped_lrc("Unlisted Song", "Nobody In Particular", build_enhanced_lrc(LINES))
        assert doc.source == "Tapped" and doc.has_word_sync
        assert abs(doc.lines[0].words[1].start_time - 1.62) < 0.01
        again = svc.get_cached_lyrics("Unlisted Song", "Nobody In Particular")
        assert again.source == "Tapped"
        svc.delete_tapped("Unlisted Song", "Nobody In Particular")
        assert svc.get_cached_tapped("Unlisted Song", "Nobody In Particular") is None
    finally:
        shutil.rmtree(CACHE, ignore_errors=True)
