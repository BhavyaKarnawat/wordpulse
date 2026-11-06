"""Syllable and timing interpolator for line-synced lyrics."""
import re
from statistics import median
from typing import List, Optional, Sequence, Tuple
from src.models.lyrics import LyricWord


class SyllableInterpolator:
    """Estimates musical syllable pacing to interpolate word timings for lines without word timestamps."""

    VOWEL_PATTERN = re.compile(r"[aeiouy]+", re.IGNORECASE)

    def estimate_syllables(self, word: str) -> int:
        """Heuristic syllable counter for English and Latin languages."""
        clean = re.sub(r"[^a-zA-Z]", "", word).lower()
        if not clean:
            return 1
        
        # Count vowel groups
        matches = self.VOWEL_PATTERN.findall(clean)
        count = len(matches)

        # Silent 'e' at end of word (e.g. "life", "time", but not "the")
        if clean.endswith("e") and not clean.endswith("le") and len(clean) > 2 and count > 1:
            count -= 1
        
        # Double vowels or common diphthongs already handled by + in regex
        return max(1, count)

    def calculate_word_weights(self, words: List[str]) -> List[float]:
        """Calculates relative duration weight for each word in a lyric line."""
        weights = []
        for word in words:
            syllables = self.estimate_syllables(word)
            char_len = len(word)
            
            # Base weight combines syllable count and raw character count
            weight = (syllables * 1.5) + (char_len * 0.15)
            
            # Ending punctuation indicates a pause or hold
            if word.endswith((",", ";", ":")):
                weight += 0.8
            elif word.endswith((".", "!", "?", "—", "-")):
                weight += 1.2
                
            weights.append(max(0.5, weight))
        return weights

    def estimate_pace(self, lines: Sequence[Tuple[List[str], float, float]]) -> Optional[float]:
        """Learns this song's seconds-per-syllable from its own line timings.

        Lines followed quickly by the next one are sung almost back to back, so
        their duration / syllable count is a good measure of the singer's pace.
        Returns None when there isn't enough evidence (then we fall back to
        spreading words across the line).
        """
        samples = []
        for words, start, end in lines:
            span = end - start
            sylls = sum(self.estimate_syllables(w) for w in words)
            if sylls >= 3 and 0.8 <= span <= 5.0:
                samples.append(span / sylls)
        if len(samples) < 3:
            return None
        # the tighter half of lines are the ones without trailing pauses
        samples.sort()
        return max(0.12, min(0.6, median(samples[: max(3, len(samples) // 2)])))

    def interpolate(self, words: List[str], start_time: float, end_time: float,
                    pace: Optional[float] = None) -> List[LyricWord]:
        """Distributes word start and end times across the line duration.

        With a known `pace` (seconds per syllable) the line is sung at that speed
        and any leftover time becomes a pause at the end, instead of stretching
        every word to fill the gap before the next line.
        """
        if not words:
            return []

        duration = max(0.4, end_time - start_time)
        weights = self.calculate_word_weights(words)
        total_weight = sum(weights) or 1.0

        # Allocate 88% of line time to singing, leaving 12% breathing/release room at the end
        singing_duration = duration * 0.88 if len(words) > 1 else duration * 0.95
        if pace:
            sylls = sum(self.estimate_syllables(w) for w in words)
            natural = sylls * pace * 1.15 + 0.15 * len(words)
            singing_duration = min(singing_duration, max(natural, 0.3 * len(words)))

        lyric_words = []
        current_time = start_time
        for idx, (word, weight) in enumerate(zip(words, weights)):
            word_duration = (weight / total_weight) * singing_duration
            word_end = current_time + word_duration

            # For the last word, we can extend slightly into the trailing buffer
            if idx == len(words) - 1:
                word_end = min(end_time, current_time + word_duration * 1.1)

            lyric_words.append(LyricWord(
                text=word,
                start_time=round(current_time, 3),
                end_time=round(word_end, 3)
            ))
            current_time = word_end

        return lyric_words
