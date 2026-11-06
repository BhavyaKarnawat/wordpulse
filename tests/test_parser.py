import pytest
from src.core.parser import LRCParser
from src.core.interpolator import SyllableInterpolator

SAMPLE_ENHANCED_LRC = """
[ti:Neon Tide]
[ar:Low Harbor]
[00:00.42] <00:00.42> Hold <00:00.90> on <00:01.30> to <00:01.60> the <00:02.10> light?
[00:04.03] <00:04.03> Will <00:04.50> you <00:04.90> wait <00:05.30> tonight?
[00:07.58] <00:07.58> Running <00:08.20> down <00:08.50> the <00:08.80> river
"""

SAMPLE_STANDARD_LRC = """
[00:00.42] Hold on to the light?
[00:04.03] Will you wait tonight?
[00:07.58] Running down the river
[00:10.35] Nowhere left to hide
"""

SAMPLE_PLAIN_TEXT = """
Hold on to the light?
Will you wait tonight?
Running down the river
"""

def test_parse_enhanced_lrc():
    parser = LRCParser()
    doc = parser.parse(SAMPLE_ENHANCED_LRC, title="Neon Tide", artist="Low Harbor")
    
    assert doc.is_synced is True
    assert doc.has_word_sync is True
    assert len(doc.lines) == 3
    
    line0 = doc.lines[0]
    assert line0.text == "Hold on to the light?"
    assert pytest.approx(line0.start_time, 0.01) == 0.42
    assert len(line0.words) == 5
    assert line0.words[0].text == "Hold"
    assert pytest.approx(line0.words[0].start_time, 0.01) == 0.42
    assert pytest.approx(line0.words[0].end_time, 0.01) == 0.90

def test_parse_standard_lrc_with_interpolation():
    parser = LRCParser()
    doc = parser.parse(SAMPLE_STANDARD_LRC, title="Neon Tide", artist="Low Harbor")
    
    assert doc.is_synced is True
    assert len(doc.lines) == 4
    
    line0 = doc.lines[0]
    assert line0.text == "Hold on to the light?"
    assert pytest.approx(line0.start_time, 0.01) == 0.42
    assert line0.end_time <= 4.03
    # Word interpolation should generate words for standard LRC
    assert len(line0.words) == 5
    assert [w.text for w in line0.words] == ["Hold", "on", "to", "the", "light?"]
    # Check that word start times are strictly increasing
    for i in range(len(line0.words) - 1):
        assert line0.words[i].start_time < line0.words[i+1].start_time
        assert line0.words[i].end_time <= line0.words[i+1].start_time

def test_parse_plain_text():
    parser = LRCParser()
    doc = parser.parse(SAMPLE_PLAIN_TEXT, title="Neon Tide", artist="Low Harbor")
    
    assert doc.is_synced is False
    assert len(doc.lines) == 3
    assert doc.lines[0].text == "Hold on to the light?"

def test_syllable_interpolator_weights():
    interpolator = SyllableInterpolator()
    count_short = interpolator.estimate_syllables("hi")
    count_long = interpolator.estimate_syllables("supercalifragilistic")
    assert count_short < count_long
    assert count_short >= 1
    assert count_long >= 5

def test_active_word_progression():
    parser = LRCParser()
    doc = parser.parse(SAMPLE_ENHANCED_LRC, title="Neon Tide", artist="Low Harbor")
    
    # At t=0.5s: Line 0 ("Hold on to the light?"), word 0
    line_idx, word_idx = doc.get_active_indices(0.50)
    assert line_idx == 0
    assert word_idx == 0
    
    # At t=1.0s: Line 0, word 1
    line_idx, word_idx = doc.get_active_indices(1.0)
    assert line_idx == 0
    assert word_idx == 1
    
    # At t=4.2s: Line 1 ("Will you wait tonight?"), word 0
    line_idx, word_idx = doc.get_active_indices(4.2)
    assert line_idx == 1
    assert word_idx == 0



PACED_LRC = """
[00:01.00] Lanterns drift across the bay
[00:03.20] Every window holds a light
[00:05.30] Quiet rooms and open doors
[00:07.50] Walking slowly through the night
[00:09.60] Hold on
[00:20.00] Morning finds us on the road
"""

def test_line_synced_words_keep_singer_pace():
    doc = LRCParser().parse(PACED_LRC)
    assert doc.has_word_sync is False
    short_line = doc.lines[4]           # two words followed by a ~10s instrumental gap
    assert short_line.text == "Hold on"
    # words are sung at the song's pace, not stretched across the whole gap
    assert short_line.words[-1].end_time - short_line.start_time < 2.5
    # dense lines still use most of their slot
    dense = doc.lines[0]
    assert dense.words[-1].end_time > dense.start_time + 1.2
