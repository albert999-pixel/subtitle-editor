"""Export edited captions in editor order with valid, non-overlapping SRT times.

Timing alignment is approximate after text edits. Caption text and order are
preserved; short or conflicting intervals are extended/shifted forward.
"""

from difflib import SequenceMatcher
from html import escape
import math
import re

MIN_CAPTION_MS = 500


def _normalize(word):
    return re.sub(r"[^\w]", "", word.casefold())


def _source_tokens(words_data):
    """Flatten recognizer entries, including entries containing several words."""
    tokens, intervals = [], []
    for item in words_data:
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        start = max(0.0, start)
        end = max(start, end)
        parts = str(item.get("word", "")).split()
        for index, part in enumerate(parts):
            tokens.append(_normalize(part))
            intervals.append((
                start + (end - start) * index / len(parts),
                start + (end - start) * (index + 1) / len(parts),
            ))
    return tokens, intervals


def _align_timings(edited_tokens, words_data):
    """Align whole sequences, rather than looking up occurrences independently.

    Replacements inherit the replaced source span. Insertions use the span
    between neighboring source words. With no usable source, export still
    retains every caption; the final scheduler supplies its minimum duration.
    """
    source, intervals = _source_tokens(words_data)
    result = [(0.0, 0.0)] * len(edited_tokens)
    matcher = SequenceMatcher(None, source, edited_tokens, autojunk=False)
    for tag, src_start, src_end, dst_start, dst_end in matcher.get_opcodes():
        if tag == "delete":
            continue
        if tag == "equal":
            result[dst_start:dst_end] = intervals[src_start:src_end]
            continue
        if src_start < src_end:
            start = intervals[src_start][0]
            end = max(start, intervals[src_end - 1][1])
        else:
            start = intervals[src_start - 1][1] if src_start else 0.0
            end = intervals[src_start][0] if src_start < len(intervals) else start
            end = max(start, end)
        count = dst_end - dst_start
        for offset in range(count):
            result[dst_start + offset] = (
                start + (end - start) * offset / count,
                start + (end - start) * (offset + 1) / count,
            )
    return result


def _format_ms(milliseconds):
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def build_srt_content(lines, words_data):
    """Return (SRT, count): one block per nonempty editor row, in that order.

    Time is rounded to integer milliseconds before scheduling. Each block lasts
    at least 500 ms, and starts no earlier than the previous block's end. This
    may move captions beyond the original audio; it never drops their text.
    """
    captions, edited = [], []
    for line in lines:
        text = " ".join(str(line.get("text", "")).splitlines()).strip()
        tokens = text.split()
        if not tokens:
            continue
        offset = len(edited)
        edited.extend(_normalize(token) for token in tokens)
        captions.append((line, text, offset, len(edited)))

    timings = _align_timings(edited, words_data)
    blocks, previous_end = [], 0
    for number, (line, text, first, last) in enumerate(captions, 1):
        interval = timings[first:last]
        start = max(previous_end, round(interval[0][0] * 1000))
        end = max(start + MIN_CAPTION_MS, round(max(t[1] for t in interval) * 1000))
        content = "<b>" + escape(text, quote=False) + "</b>"
        blocks.append(f"{number}\n{_format_ms(start)} --> {_format_ms(end)}\n{content}")
        previous_end = end
    return "\n\n".join(blocks), len(blocks)
