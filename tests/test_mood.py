from src.core.mood import classify, word_rate
from src.core.parser import LRCParser


def test_rap_by_tags_or_word_density():
    assert classify(95, 0.6, 0.5, 0.1, 1.5, ["west coast hip hop"])[0] == "NEON"
    mood, eff, _ = classify(88, 0.6, 0.5, 0.1, 3.4, [])      # half-time beat, very dense words
    assert mood == "NEON" and eff == 176


def test_heavy_needs_metal_or_harsh_rock():
    assert classify(150, 0.7, 0.8, 0.3, 2.0, ["thrash metal"])[0] == "HEAVY"
    assert classify(120, 0.7, 0.3, 0.1, 2.0, ["pop rock"])[0] == "BRIGHT"   # gentle rock isn't heavy


def test_tempo_bands_without_tags():
    assert classify(70, 0.6, 0.2, 0.05, 1.2, [])[0] == "SOFT"
    assert classify(96, 0.6, 0.4, 0.05, 1.8, [])[0] == "SMOOTH"
    assert classify(122, 0.6, 0.5, 0.08, 2.0, [])[0] == "BRIGHT"
    assert classify(150, 0.6, 0.6, 0.1, 2.0, [])[0] == "NEON"


def test_low_confidence_tempo_is_ignored():
    mood, eff, _ = classify(150, 0.05, 0.6, 0.1, 1.4, [])
    assert eff == 0 and mood == "SOFT"


def test_word_rate_from_timed_lyrics():
    lrc = "\n".join([
        "[00:01.00] <00:01.00> one <00:01.25> two <00:01.50> three <00:01.75> four <00:02.00> five",
        "[00:03.00] <00:03.00> six <00:03.25> seven <00:03.50> eight <00:03.75> nine <00:04.00> ten",
        "[00:05.00] <00:05.00> a <00:05.25> b <00:05.50> c <00:05.75> d <00:06.00> e",
    ])
    rate = word_rate(LRCParser().parse(lrc))
    assert 3.0 < rate < 5.5        # five words a second, give or take the last word's length
