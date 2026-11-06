"""High-resolution album art for the fullscreen views.

Windows only hands apps a small thumbnail of the cover (often 300 px), which looks
soft when it fills a screen. Apple's public iTunes Search API (free, no key) returns
the same cover at up to 1200 px. Only the song title and artist are sent; results
are cached on disk so each song is looked up once.
"""
import json
import logging
import re
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("wordpulse")
SEARCH = "https://itunes.apple.com/search?term={q}&entity=song&limit=8"


def _norm(s: str) -> str:
    s = re.sub(r"[\(\[].*?[\)\]]", "", s or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class ArtworkFinder:
    def __init__(self, cache_path: Optional[Path] = None):
        self.cache_path = cache_path
        self.cache: Dict[str, str] = {}
        if cache_path and cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}
        self._lock = threading.Lock()

    def lookup(self, title: str, artist: str) -> str:
        """URL of a large cover, or "" if none was found (also cached, so we don't keep asking)."""
        key = f"{_norm(artist)} - {_norm(title)}"
        if key in self.cache:
            return self.cache[key]
        url = ""
        try:
            q = urllib.parse.quote(f"{title} {artist}")
            req = urllib.request.Request(SEARCH.format(q=q), headers={"User-Agent": "WordPulse/1.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                results = json.loads(resp.read().decode("utf-8")).get("results", [])
            want_t, want_a = _norm(title), _norm(artist)
            for r in results:
                a, t = _norm(r.get("artistName", "")), _norm(r.get("trackName", ""))
                if (want_a and (want_a in a or a in want_a)) and (want_t and (want_t in t or t in want_t)):
                    small = r.get("artworkUrl100", "")
                    url = re.sub(r"/\d+x\d+bb\.", "/1200x1200bb.", small) if small else ""
                    break
        except Exception as e:
            log.info("Artwork lookup failed for %s: %s", title, e.__class__.__name__)
            return ""            # not cached: try again next time (e.g. we were offline)
        with self._lock:
            self.cache[key] = url
            if self.cache_path:
                try:
                    self.cache_path.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")
                except Exception:
                    pass
        return url
