"""Original demo songs (written for WordPulse) with generated word-level timings.

These are not real recordings: the titles, artists and lyrics are placeholders
so demo mode can show word-by-word sync without bundling anyone's lyrics.
"""
from typing import Dict, List

_SONGS = [
    {
        "title": "Neon Tide",
        "artist": "Low Harbor",
        "album": "Harbor Lights",
        "app_name": "Spotify",
        "lines": [
            "Wait for the light to come home",
            "Tell me the night is still young",
            "I can hear your heart in the city",
            "Every star is falling for you",
            "Call me when the morning wakes",
            "We could dance until the sun",
            "Hold my hand and never let go",
            "Neon tide is pulling me in",
        ],
    },
    {
        "title": "Paper Satellites",
        "artist": "The Quiet Arcade",
        "album": "Signal",
        "app_name": "Apple Music",
        "lines": [
            "I folded my words into paper",
            "And threw them up into the sky",
            "Paper satellites around the moon",
            "Sending you a signal every night",
            "Can you see me waving from the roof",
            "Write my name across the stars",
            "One more minute on the line",
            "Then I will fly back down to you",
        ],
    },
    {
        "title": "Slow Motion Summer",
        "artist": "Mara Vell",
        "album": "Heatwave Postcards",
        "app_name": "Spotify",
        "lines": [
            "Sunlight melting on the road",
            "Your laugh is ringing like a bell",
            "Slow motion summer in my head",
            "Ice cream dripping on your hand",
            "We were running to the ocean",
            "Time was standing still for us",
            "Tell me this will never end",
            "Slow motion summer stay with me",
        ],
    },
]

_INTRO = 2.0       # seconds before the first word
_LINE_GAP = 0.9    # pause between lines
_REPEATS = 2       # play the verse twice


def _ts(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def _build_lrc(lines: List[str]) -> (str, float):
    t = _INTRO
    out = []
    for line in lines * _REPEATS:
        parts = [f"[{_ts(t)}]"]
        for word in line.split():
            parts.append(f"<{_ts(t)}> {word}")
            t += 0.34 + min(0.36, 0.045 * len(word))
        out.append(" ".join(parts))
        t += _LINE_GAP
    return "\n".join(out), t + 3.0


BUILTIN_LYRICS: Dict[str, str] = {}
DEMO_TRACKS: List[dict] = []

for _song in _SONGS:
    _lrc, _duration = _build_lrc(_song["lines"])
    # same normalisation as LyricsService._normalize_key, so lookups match exactly
    _key = "".join(c for c in f"{_song['artist']} - {_song['title']}".lower() if c.isalnum() or c.isspace()).strip()
    BUILTIN_LYRICS[_key] = _lrc
    DEMO_TRACKS.append({
        "title": _song["title"],
        "artist": _song["artist"],
        "album": _song["album"],
        "duration": round(_duration, 2),
        "app_name": _song["app_name"],
    })
