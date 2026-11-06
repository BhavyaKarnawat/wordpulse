"""Lyrics models for line and word synchronization."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class LyricWord:
    text: str
    start_time: float
    end_time: float
    icon: Optional[str] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def is_active(self, current_time: float) -> bool:
        return self.start_time <= current_time <= self.end_time

    def is_past(self, current_time: float) -> bool:
        return current_time > self.end_time


@dataclass
class LyricLine:
    text: str
    start_time: float
    end_time: float
    words: List[LyricWord] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def contains_time(self, current_time: float) -> bool:
        return self.start_time <= current_time <= self.end_time

    def get_active_word_index(self, current_time: float) -> int:
        """Find the index of the word currently being sung or most recently completed in this line."""
        if not self.words:
            return -1
        
        for idx, word in enumerate(self.words):
            if word.is_active(current_time):
                return idx
        
        # If past the start but between words or after the last word
        if current_time >= self.start_time:
            last_past = -1
            for idx, word in enumerate(self.words):
                if current_time >= word.start_time:
                    last_past = idx
            return last_past
        
        return -1


@dataclass
class LyricsDocument:
    track_title: str
    artist: str
    lines: List[LyricLine] = field(default_factory=list)
    is_synced: bool = False
    has_word_sync: bool = False
    source: str = "LRCLIB"

    def get_active_indices(self, current_time: float) -> Tuple[int, int]:
        """Returns (active_line_index, active_word_index) for the given timestamp."""
        if not self.lines:
            return -1, -1

        # Find line
        active_line = -1
        for idx, line in enumerate(self.lines):
            # If current_time is within this line or before next line
            next_start = self.lines[idx + 1].start_time if idx + 1 < len(self.lines) else line.end_time + 4.0
            if line.start_time <= current_time < next_start:
                active_line = idx
                break
        
        if active_line == -1:
            # If before first line
            if current_time < self.lines[0].start_time:
                return -1, -1
            # If after last line
            active_line = len(self.lines) - 1

        active_word = self.lines[active_line].get_active_word_index(current_time)
        return active_line, active_word

