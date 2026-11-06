import pytest
from src.core.icon_mapper import LyricIconMapper

def test_icon_mapper_basic_words():
    mapper = LyricIconMapper()
    assert mapper.get_icon("love") is not None
    assert mapper.get_icon("fire") is not None
    assert mapper.get_icon("rain") is not None
    assert mapper.get_icon("heart") is not None

def test_icon_mapper_punctuation_and_casing():
    mapper = LyricIconMapper()
    # Punctuation and casing should be stripped cleanly
    assert mapper.get_icon("Love!") == mapper.get_icon("love")
    assert mapper.get_icon("HEART...") == mapper.get_icon("heart")
    assert mapper.get_icon('"fire"') == mapper.get_icon("fire")

def test_icon_mapper_plurals_and_variations():
    mapper = LyricIconMapper()
    # Plural / variation should match root
    assert mapper.get_icon("tears") is not None
    assert mapper.get_icon("stars") is not None
    assert mapper.get_icon("dancing") is not None
    assert mapper.get_icon("crying") is not None

def test_enrich_lyrics_document():
    from src.core.parser import LRCParser
    parser = LRCParser()
    lrc = "[00:01.00] I feel your heart and see the stars in the night"
    doc = parser.parse(lrc)
    mapper = LyricIconMapper()
    enriched = mapper.enrich_document(doc)
    
    # Check that words like "heart", "stars", "night" received icons
    words = enriched.lines[0].words
    heart_word = next(w for w in words if "heart" in w.text.lower())
    stars_word = next(w for w in words if "stars" in w.text.lower())
    night_word = next(w for w in words if "night" in w.text.lower())
    
    assert heart_word.icon is not None
    assert stars_word.icon is not None
    assert night_word.icon is not None

