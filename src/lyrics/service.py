"""Lyrics service for fetching, caching, and enriching synchronized lyrics."""
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional
from src.core.icon_mapper import LyricIconMapper
from src.core.parser import LRCParser
from src.lyrics.builtin_lyrics import BUILTIN_LYRICS
from src.models.lyrics import LyricLine, LyricWord, LyricsDocument

try:
    import syncedlyrics
    HAS_SYNCEDLYRICS = True
except ImportError:
    HAS_SYNCEDLYRICS = False


class LyricsService:
    """Manages fetching, disk caching, parsing, and icon-enrichment of lyrics."""

    LRCLIB_GET_URL = "https://lrclib.net/api/get"
    LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
    NOT_FOUND_DAYS = 3

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        parser: Optional[LRCParser] = None,
        icon_mapper: Optional[LyricIconMapper] = None,
    ):
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".wordpulse" / "lyrics_cache"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:                 # home folder not writable: cache in the temp folder instead
            import tempfile
            self.cache_dir = Path(tempfile.gettempdir()) / "WordPulse" / "lyrics_cache"
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.parser = parser or LRCParser()
        self.icon_mapper = icon_mapper or LyricIconMapper()

    def _normalize_key(self, title: str, artist: str) -> str:
        clean_title = re.sub(r"[\(\[].*?[\)\]]", "", title)  # Strip (Remastered), [Live], etc.
        clean = f"{artist} - {clean_title}".lower()
        return "".join(c for c in clean if c.isalnum() or c.isspace()).strip()

    def _get_cache_path(self, norm_key: str) -> Path:
        safe_filename = "".join(c if c.isalnum() or c in "-_" else "_" for c in norm_key)[:120]
        return self.cache_dir / f"{safe_filename}.json"

    def _fetch_from_lrclib(self, title: str, artist: str, duration: float = 0.0) -> Optional[str]:
        """Queries the public LRCLIB API for synced or plain lyrics."""
        clean_title = re.sub(r"[\(\[].*?[\)\]]", "", title).strip()
        params = {"track_name": clean_title, "artist_name": artist}
        if duration > 0:
            params["duration"] = str(int(duration))

        self.last_fetch_offline = False
        net_errors = 0

        # 1. Direct GET
        try:
            url = f"{self.LRCLIB_GET_URL}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={"User-Agent": "WordPulse/1.2 (lyrics display for Windows)"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    synced = data.get("syncedLyrics")
                    if synced:
                        return synced
                    plain = data.get("plainLyrics")
                    if plain:
                        return plain
        except urllib.error.HTTPError:
            pass                     # the server answered (e.g. 404 = not in its database)
        except Exception:
            net_errors += 1          # no connection, DNS failure, timeout...

        # 2. Search fallback
        try:
            search_query = f"{clean_title} {artist}".strip()
            url = f"{self.LRCLIB_SEARCH_URL}?q={urllib.parse.quote(search_query)}"
            req = urllib.request.Request(url, headers={"User-Agent": "WordPulse/1.2 (lyrics display for Windows)"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                if resp.status == 200:
                    results = json.loads(resp.read().decode("utf-8"))
                    if isinstance(results, list) and len(results) > 0:
                        first = results[0]
                        synced = first.get("syncedLyrics")
                        if synced:
                            return synced
                        plain = first.get("plainLyrics")
                        if plain:
                            return plain
        except urllib.error.HTTPError:
            pass
        except Exception:
            net_errors += 1

        if net_errors == 2:
            self.last_fetch_offline = True   # both lookups failed to connect: offline, not "not found"
            return None

        # 3. syncedlyrics library fallback
        if HAS_SYNCEDLYRICS:
            try:
                lrc = syncedlyrics.search(f"{clean_title} {artist}", enhanced=True)
                if lrc:
                    return lrc
            except Exception:
                pass

        return None

    def create_empty_or_placeholder_doc(self, title: str, artist: str) -> LyricsDocument:
        """Returns a stylish placeholder when no synchronized lyrics are found."""
        placeholder_line = LyricLine(
            text="No synced lyrics available for this track",
            start_time=0.0,
            end_time=999.0,
            words=[LyricWord(text="No", start_time=0.0, end_time=999.0),
                   LyricWord(text="synced", start_time=0.0, end_time=999.0),
                   LyricWord(text="lyrics", start_time=0.0, end_time=999.0, icon="🎵"),
                   LyricWord(text="available", start_time=0.0, end_time=999.0)]
        )
        return LyricsDocument(
            track_title=title,
            artist=artist,
            lines=[placeholder_line],
            is_synced=False,
            has_word_sync=False,
            source="None"
        )

    def get_cached_lyrics(self, title: str, artist: str) -> Optional[LyricsDocument]:
        """Fast synchronous check for built-in or cached lyrics without network I/O."""
        norm_key = self._normalize_key(title, artist)

        # 0. Your own tap-synced timing always wins
        tapped = self.get_cached_tapped(title, artist)
        if tapped:
            return tapped

        # 1. Built-in instant matches
        for b_key, raw_lrc in BUILTIN_LYRICS.items():
            if b_key in norm_key or norm_key in b_key:
                doc = self.parser.parse(raw_lrc, title=title, artist=artist)
                return self.icon_mapper.enrich_document(doc)

        # 2. Local Disk Cache
        cache_path = self._get_cache_path(norm_key)
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                raw_lrc = cached_data.get("raw_lrc")
                if raw_lrc:
                    doc = self.parser.parse(raw_lrc, title=title, artist=artist)
                    if cached_data.get("source"):
                        doc.source = cached_data["source"]
                    return self.icon_mapper.enrich_document(doc)
            except Exception:
                # a damaged cache file (half-written, edited by hand...): drop it and fetch again
                logging.getLogger("wordpulse").warning("Ignoring damaged lyrics cache file %s", cache_path.name)
                try:
                    cache_path.unlink()
                except OSError:
                    pass
        return None

    def _tapped_path(self, title: str, artist: str) -> Path:
        return self._get_cache_path(self._normalize_key(title, artist)).with_suffix(".tapped.json")

    def get_cached_tapped(self, title: str, artist: str) -> Optional[LyricsDocument]:
        path = self._tapped_path(title, artist)
        if not path.exists():
            return None
        try:
            raw_lrc = json.loads(path.read_text(encoding="utf-8")).get("raw_lrc")
        except Exception:
            return None
        if not raw_lrc:
            return None
        doc = self.parser.parse(raw_lrc, title=title, artist=artist)
        doc.source = "Tapped"
        return self.icon_mapper.enrich_document(doc)

    def save_tapped_lrc(self, title: str, artist: str, raw_lrc: str) -> LyricsDocument:
        """Stores word timings you tapped; kept separate so a re-fetch never overwrites them."""
        path = self._tapped_path(title, artist)
        path.write_text(json.dumps({"title": title, "artist": artist, "raw_lrc": raw_lrc}, indent=2), encoding="utf-8")
        return self.get_cached_tapped(title, artist)

    def delete_tapped(self, title: str, artist: str) -> None:
        path = self._tapped_path(title, artist)
        if path.exists():
            path.unlink()

    # ---- fixing wrong lyrics ----
    def _http_json(self, url: str):
        req = urllib.request.Request(url, headers={"User-Agent": "WordPulse/1.2 (lyrics display for Windows)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def search_alternatives(self, title: str, artist: str, query: str = "") -> list:
        """Other lyric versions on LRCLIB for this song (or a custom search)."""
        clean_title = re.sub(r"[\(\[].*?[\)\]]", "", title).strip()
        q = query.strip() or f"{clean_title} {artist}".strip()
        try:
            results = self._http_json(f"{self.LRCLIB_SEARCH_URL}?q={urllib.parse.quote(q)}")
        except Exception:
            return []
        out = []
        for r in results[:25] if isinstance(results, list) else []:
            synced = r.get("syncedLyrics") or ""
            out.append({
                "id": r.get("id"),
                "title": r.get("trackName") or "",
                "artist": r.get("artistName") or "",
                "album": r.get("albumName") or "",
                "duration": r.get("duration") or 0,
                "timing": "words" if re.search(r"<\d+:\d+", synced) else ("lines" if synced else "none"),
                "instrumental": bool(r.get("instrumental")),
            })
        return out

    def _store_override(self, title: str, artist: str, raw_lrc: str, source: str) -> LyricsDocument:
        """Replaces the cached lyrics for this song; old taps no longer match the words, so they go."""
        cache_path = self._get_cache_path(self._normalize_key(title, artist))
        cache_path.write_text(json.dumps({"title": title, "artist": artist, "raw_lrc": raw_lrc, "source": source},
                                         indent=2), encoding="utf-8")
        self.delete_tapped(title, artist)
        doc = self.parser.parse(raw_lrc, title=title, artist=artist)
        doc.source = source
        return self.icon_mapper.enrich_document(doc)

    def use_alternative(self, title: str, artist: str, lrclib_id: int) -> Optional[LyricsDocument]:
        try:
            data = self._http_json(f"https://lrclib.net/api/get/{int(lrclib_id)}")
        except Exception:
            return None
        raw = data.get("syncedLyrics") or data.get("plainLyrics")
        return self._store_override(title, artist, raw, "LRCLIB") if raw else None

    def import_lyrics(self, title: str, artist: str, text: str) -> Optional[LyricsDocument]:
        """Your own .lrc file or pasted lyrics (plain text can then be tap-synced)."""
        text = (text or "").strip()
        if not text:
            return None
        return self._store_override(title, artist, text[:200_000], "Imported")

    def get_lyrics(self, title: str, artist: str, duration: float = 0.0) -> LyricsDocument:
        """Main entry point: checks builtin, checks cache, fetches network, parses, and enriches."""
        cached = self.get_cached_lyrics(title, artist)
        if cached:
            return cached

        norm_key = self._normalize_key(title, artist)
        cache_path = self._get_cache_path(norm_key)
        none_path = cache_path.with_suffix(".none.json")

        # recently looked up and nothing exists: don't ask again on every play
        if none_path.exists() and time.time() - none_path.stat().st_mtime < self.NOT_FOUND_DAYS * 86400:
            return self.create_empty_or_placeholder_doc(title, artist)

        # 3. Online fetch
        self.last_fetch_offline = False
        raw_lrc = self._fetch_from_lrclib(title, artist, duration)
        if raw_lrc:
            # Save to cache
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"title": title, "artist": artist, "raw_lrc": raw_lrc}, f, indent=2)
            except Exception:
                pass

            try:
                doc = self.parser.parse(raw_lrc, title=title, artist=artist)
                return self.icon_mapper.enrich_document(doc)
            except Exception:
                logging.getLogger("wordpulse").exception("Couldn't read the lyrics found for %s", title)
                try:
                    cache_path.unlink()
                except OSError:
                    pass
                return self.create_empty_or_placeholder_doc(title, artist)

        # 4. Offline: say so (the app retries later); nothing is remembered
        if getattr(self, "last_fetch_offline", False):
            doc = self.create_empty_or_placeholder_doc(title, artist)
            doc.source = "Offline"
            return doc

        # 5. Genuinely not found: remember that for a few days
        try:
            none_path.write_text(json.dumps({"title": title, "artist": artist}), encoding="utf-8")
        except Exception:
            pass
        return self.create_empty_or_placeholder_doc(title, artist)

    def prune_cache(self, max_files: int = 4000) -> int:
        """Keeps the cache from growing forever; your taps and imported lyrics are never removed."""
        files = [f for f in self.cache_dir.glob("*.json") if not f.name.endswith(".tapped.json")]
        if len(files) <= max_files:
            return 0
        files.sort(key=lambda f: f.stat().st_mtime)
        removed = 0
        for f in files[: len(files) - max_files]:
            try:
                if not f.name.endswith(".none.json") and \
                        json.loads(f.read_text(encoding="utf-8")).get("source") == "Imported":
                    continue
                f.unlink()
                removed += 1
            except Exception:
                pass
        return removed

