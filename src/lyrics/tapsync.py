"""Turn tap-to-sync results into word-timed (enhanced) LRC.

The sync window sends every line with its words. Words the user tapped carry
`tapped: true` and an exact `start_time`; untapped words keep the estimate they
already had. We clean the result up (taps must move forward in time) and write
standard enhanced LRC, so the normal parser and cache handle it from then on.
"""
from typing import Dict, List


def _ts(t: float) -> str:
    t = max(0.0, t)
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def build_enhanced_lrc(lines: List[Dict]) -> str:
    out = []
    last = 0.0
    for line in lines:
        words = [w for w in line.get("words", []) if str(w.get("text", "")).strip()]
        if not words:
            continue
        times = []
        for w in words:
            t = float(w.get("start_time", 0.0))
            # keep strictly increasing; a late/duplicate tap can't jump backwards
            t = max(t, last + 0.02) if times or out else max(t, 0.0)
            times.append(t)
            last = t
        line_start = min(float(line.get("start_time", times[0])), times[0])
        parts = [f"[{_ts(line_start)}]"]
        parts += [f"<{_ts(t)}> {str(w['text']).strip()}" for w, t in zip(words, times)]
        out.append(" ".join(parts))
    return "\n".join(out) + "\n"


def tapped_count(lines: List[Dict]) -> int:
    return sum(1 for line in lines for w in line.get("words", []) if w.get("tapped"))
