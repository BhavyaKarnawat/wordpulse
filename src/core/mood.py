"""Turns tempo, energy, lyric density and genre tags into one of five moods."""
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("wordpulse")

MOODS = ["NEON", "BRIGHT", "HEAVY", "SMOOTH", "SOFT"]
MOOD_LABELS = {"NEON": "Neon", "BRIGHT": "Bright", "HEAVY": "Heavy", "SMOOTH": "Smooth", "SOFT": "Soft"}
from src.models.settings import DEFAULT_MOOD_STYLES  # noqa: E402  (pools of styles per mood)

HEAVY_TAGS = {"metal", "heavy metal", "hard rock", "punk", "punk rock", "grunge", "metalcore", "nu metal",
              "thrash metal", "death metal", "hardcore", "alternative metal", "rock"}
NEON_TAGS = {"hip hop", "hip-hop", "rap", "trap", "drill", "grime", "edm", "electronic", "dubstep",
             "drum and bass", "house", "techno", "electro", "phonk", "hyperpop", "gangsta rap", "uk drill"}
SOFT_TAGS = {"ballad", "acoustic", "folk", "ambient", "classical", "singer-songwriter", "lo-fi", "lofi",
             "piano", "chill", "indie folk", "soundtrack"}
SMOOTH_TAGS = {"r&b", "rnb", "soul", "neo soul", "neo-soul", "jazz", "contemporary r&b", "funk", "bossa nova"}
BRIGHT_TAGS = {"pop", "dance", "dance-pop", "disco", "k-pop", "synthpop", "electropop", "pop rock"}


def word_rate(doc) -> float:
    """Words per second while singing (ignores gaps between lines)."""
    if not doc or not getattr(doc, "is_synced", False):
        return 0.0
    words, sung = 0, 0.0
    for line in doc.lines:
        ws = [w for w in line.words if w.text.strip()]
        if len(ws) < 2:
            continue
        # first word start -> last word start: the last word is often stretched to the next line
        span = ws[-1].start_time - ws[0].start_time
        if 0.2 < span < 12:
            words += len(ws) - 1
            sung += span
    return words / sung if sung >= 2 else 0.0


def classify(bpm: float, confidence: float, energy: float, harshness: float,
             words_per_s: float, tags: List[str]) -> Tuple[str, float, str]:
    """Returns (mood, effective_bpm, reason)."""
    raw = [t.lower() for t in tags]

    def group(terms):   # "west coast hip hop" counts as "hip hop"
        return {t for t in raw if any(term == t or f" {term}" in f" {t}" for term in terms)}

    heavy, neon, soft, smooth, bright = (group(HEAVY_TAGS - {"rock"}), group(NEON_TAGS), group(SOFT_TAGS),
                                         group(SMOOTH_TAGS), group(BRIGHT_TAGS))
    rockish = bool(group({"rock"}))
    tagset = set(raw)
    has_tempo = bpm > 0 and confidence >= 0.2
    eff = bpm if has_tempo else 0.0
    # rap is often "half time" for a beat tracker: dense words reveal the real speed
    if has_tempo and words_per_s >= 2.8 and bpm < 105:
        eff = bpm * 2
    why = []
    if eff:
        why.append(f"{eff:.0f} BPM")
    if words_per_s:
        why.append(f"{words_per_s:.1f} words/s")
    named = [t for t in raw if t in (heavy | neon | soft | smooth | bright) or (rockish and "rock" in t)][:3]
    if named:
        why.append(", ".join(named))
    reason = " · ".join(why) or "not enough information yet"

    if heavy or (rockish and (harshness > 0.22 or energy > 0.6)):
        return "HEAVY", eff, reason
    if neon or words_per_s >= 3.0 or eff >= 135:
        if energy >= 0.15 or not has_tempo:
            return "NEON", eff, reason
    if soft or (eff and eff < 82 and energy < 0.5):
        return "SOFT", eff, reason
    if smooth or (eff and 82 <= eff < 108):
        return "SMOOTH", eff, reason
    if bright or eff >= 108:
        return "BRIGHT", eff, reason
    if words_per_s and words_per_s < 1.6:
        return "SOFT", eff, reason
    return "SMOOTH", eff, reason


class GenreTags:
    """Artist genre tags from MusicBrainz (free, no key), cached on disk, max one request per second."""
    URL = "https://musicbrainz.org/ws/2/artist/?query={q}&fmt=json&limit=1"

    def __init__(self, cache_path: Optional[Path] = None):
        self.cache_path = cache_path
        self.cache: Dict[str, List[str]] = {}
        if cache_path and cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}
        self._lock = threading.Lock()
        self._last = 0.0

    def get(self, artist: str) -> Optional[List[str]]:
        return self.cache.get(artist.strip().lower())

    def fetch(self, artist: str) -> List[str]:
        key = artist.strip().lower()
        if not key or key in ("unknown artist",):
            return []
        if key in self.cache:
            return self.cache[key]
        main = re.split(r",| & | feat\.? | ft\.? | x ", artist, flags=re.I)[0].strip()
        with self._lock:
            wait = 1.1 - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
        tags: List[str] = []
        try:
            q = urllib.parse.quote(f'artist:"{main}"')
            req = urllib.request.Request(self.URL.format(q=q),
                                         headers={"User-Agent": "WordPulse/1.2 (desktop lyrics app)",
                                                  "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            artists = data.get("artists") or []
            if artists and artists[0].get("score", 0) >= 85:
                raw = sorted(artists[0].get("tags") or [], key=lambda t: -t.get("count", 0))
                tags = [t["name"].lower() for t in raw[:12]]
        except Exception as e:
            log.info("Genre lookup failed for %s: %s", main, e.__class__.__name__)
            return []          # not cached: try again next time
        self.cache[key] = tags
        if self.cache_path:
            try:
                self.cache_path.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")
            except Exception:
                pass
        return tags
