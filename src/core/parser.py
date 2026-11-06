"""Parser for standard LRC, Enhanced Syllable LRC, and plain lyrics."""
import re
from typing import List, Optional, Tuple
from src.models.lyrics import LyricLine, LyricWord, LyricsDocument
from src.core.interpolator import SyllableInterpolator


class LRCParser:
    """Parses LRC format strings into structured LyricsDocuments with word-level timestamps."""

    LINE_TAG_REGEX = re.compile(r"^\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)$")
    WORD_TAG_REGEX = re.compile(r"<(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?>\s*([^<]*)")
    META_TAG_REGEX = re.compile(r"^\[(ti|ar|al|au|by|offset|length):([^\]]+)\]", re.IGNORECASE)

    def __init__(self, interpolator: Optional[SyllableInterpolator] = None):
        self.interpolator = interpolator or SyllableInterpolator()

    @staticmethod
    def _parse_timestamp(min_s: str, sec_s: str, frac_s: Optional[str]) -> float:
        """Converts mm:ss.xx to float seconds."""
        minutes = int(min_s)
        seconds = int(sec_s)
        fraction = 0.0
        if frac_s:
            # 2 digits = hundredths (.42 -> 0.42), 3 digits = thousandths (.420 -> 0.42)
            fraction = int(frac_s) / (10 ** len(frac_s))
        return (minutes * 60) + seconds + fraction

    def parse(self, raw_lrc: str, title: str = "", artist: str = "") -> LyricsDocument:
        """Parses LRC string into a LyricsDocument with word timestamps."""
        lines_raw = raw_lrc.strip().splitlines()
        parsed_entries = []
        is_synced = False
        has_word_sync = False
        meta_title = title
        meta_artist = artist

        for raw_line in lines_raw:
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # Check metadata tags
            meta_match = self.META_TAG_REGEX.match(raw_line)
            if meta_match:
                tag, val = meta_match.group(1).lower(), meta_match.group(2).strip()
                if tag == "ti" and not meta_title:
                    meta_title = val
                elif tag == "ar" and not meta_artist:
                    meta_artist = val
                continue

            # Check line timestamp [mm:ss.xx]
            line_match = self.LINE_TAG_REGEX.match(raw_line)
            if line_match:
                is_synced = True
                start_sec = self._parse_timestamp(
                    line_match.group(1),
                    line_match.group(2),
                    line_match.group(3)
                )
                content = line_match.group(4).strip()
                
                # Check for enhanced word-level tags <mm:ss.xx> word
                word_matches = list(self.WORD_TAG_REGEX.finditer(content))
                if word_matches:
                    has_word_sync = True
                    enhanced_words = []
                    for i, wm in enumerate(word_matches):
                        w_start = self._parse_timestamp(wm.group(1), wm.group(2), wm.group(3))
                        w_text = wm.group(4).strip()
                        if not w_text:
                            continue
                        enhanced_words.append((w_start, w_text))

                    # Reconstruct clean line text
                    clean_line_text = " ".join(w[1] for w in enhanced_words)
                    parsed_entries.append({
                        "start_time": start_sec,
                        "text": clean_line_text,
                        "enhanced_words": enhanced_words
                    })
                else:
                    # Standard line LRC
                    if content:  # ignore empty placeholder sync lines
                        parsed_entries.append({
                            "start_time": start_sec,
                            "text": content,
                            "enhanced_words": None
                        })
            else:
                # Non-timestamped line (unsynced plain text)
                if raw_line:
                    parsed_entries.append({
                        "start_time": None,
                        "text": raw_line,
                        "enhanced_words": None
                    })

        # Sort synced lines chronologically
        if is_synced:
            parsed_entries.sort(key=lambda x: x["start_time"] if x["start_time"] is not None else 0.0)

        # Assemble LyricLine objects with end times and interpolated words
        lines: List[LyricLine] = []
        num_entries = len(parsed_entries)

        # Learn the singer's pace from line-synced lines so estimated words keep up
        pace_samples = []
        for i, entry in enumerate(parsed_entries):
            if entry["start_time"] is None or entry["enhanced_words"]:
                continue
            if i + 1 < num_entries and parsed_entries[i + 1]["start_time"] is not None:
                pace_samples.append((entry["text"].split(), entry["start_time"], parsed_entries[i + 1]["start_time"]))
        pace = self.interpolator.estimate_pace(pace_samples)

        for i, entry in enumerate(parsed_entries):
            line_start = entry["start_time"]
            line_text = entry["text"]
            enhanced_words = entry["enhanced_words"]

            if line_start is None:
                # Unsynced line
                words = [LyricWord(text=w, start_time=0.0, end_time=0.0) for w in line_text.split()]
                lines.append(LyricLine(
                    text=line_text,
                    start_time=0.0,
                    end_time=0.0,
                    words=words
                ))
                continue

            # Determine line end time
            if i + 1 < num_entries and parsed_entries[i + 1]["start_time"] is not None:
                next_start = parsed_entries[i + 1]["start_time"]
                # Cap line duration at 8 seconds to prevent lingering during long instrumental breaks
                line_end = min(next_start, line_start + 7.5)
            else:
                line_end = line_start + 4.5

            if enhanced_words:
                # Build words from enhanced word tags
                words = []
                for w_idx, (w_start, w_text) in enumerate(enhanced_words):
                    if w_idx + 1 < len(enhanced_words):
                        w_end = enhanced_words[w_idx + 1][0]
                    else:
                        w_end = line_end
                    words.append(LyricWord(
                        text=w_text,
                        start_time=round(w_start, 3),
                        end_time=round(max(w_start + 0.1, w_end), 3)
                    ))
            else:
                # Interpolate word timings for standard LRC
                raw_words = line_text.split()
                words = self.interpolator.interpolate(raw_words, line_start, line_end, pace=pace)

            lines.append(LyricLine(
                text=line_text,
                start_time=round(line_start, 3),
                end_time=round(line_end, 3),
                words=words
            ))

        return LyricsDocument(
            track_title=meta_title or title,
            artist=meta_artist or artist,
            lines=lines,
            is_synced=is_synced,
            has_word_sync=has_word_sync
        )

