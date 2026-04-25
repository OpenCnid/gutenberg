"""Boundary-aware text chunking with overlap."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass
class ChunkInfo:
    id: str
    char_start: int
    char_end: int
    text: str
    estimated_tokens: int
    heading_context: list[str] = field(default_factory=list)


# Patterns for boundary detection
_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_BLANK_LINE_RE = re.compile(r"\n\n")
_SENTENCE_RE = re.compile(r"[.!?]\s")
_WHITESPACE_RE = re.compile(r"\s")


def _estimate_tokens(char_count: int) -> int:
    """Estimate tokens as ceil(chars / 4)."""
    return math.ceil(char_count / 4)


def _find_best_boundary(text: str, target: int, window_start: int) -> int:
    """Find the best split point in text[window_start:target] by boundary preference.

    Search backward from target for the highest-priority boundary:
    1. Markdown heading (start of line with # )
    2. Blank line (paragraph boundary)
    3. Sentence-ending punctuation followed by whitespace
    4. Any whitespace
    5. Hard cut at target (last resort)
    """
    if window_start >= target:
        return target

    region = text[window_start:target]

    # 1. Heading boundary — find the last heading start in the region
    best = -1
    for m in _HEADING_RE.finditer(region):
        # Split before the heading line — find the newline before it
        pos = m.start()
        if pos > 0:
            best = window_start + pos
    if best > window_start:
        return best

    # 2. Blank line boundary
    best = -1
    for m in _BLANK_LINE_RE.finditer(region):
        pos = m.end()
        if pos <= len(region):
            best = window_start + pos
    if best > window_start:
        return best

    # 3. Sentence boundary
    best = -1
    for m in _SENTENCE_RE.finditer(region):
        pos = m.end()
        if pos <= len(region):
            best = window_start + pos
    if best > window_start:
        return best

    # 4. Whitespace boundary
    best = -1
    for m in _WHITESPACE_RE.finditer(region):
        pos = m.end()
        if pos <= len(region):
            best = window_start + pos
    if best > window_start:
        return best

    # 5. Hard cut
    return target


def _extract_headings(text: str) -> list[str]:
    """Extract the heading stack active at the end of text."""
    headings: list[str] = []
    for m in _HEADING_RE.finditer(text):
        line_end = text.find("\n", m.start())
        if line_end == -1:
            line_end = len(text)
        heading_line = text[m.start():line_end].strip()
        level = len(heading_line) - len(heading_line.lstrip("#"))
        heading_text = heading_line.lstrip("#").strip()

        # Maintain a stack: pop headings at same or deeper level
        while headings and _heading_level(headings[-1]) >= level:
            headings.pop()
        headings.append("#" * level + " " + heading_text)

    return headings


def _heading_level(heading: str) -> int:
    """Get the level of a heading string like '## Foo'."""
    return len(heading) - len(heading.lstrip("#"))


def chunk_text(
    text: str,
    chunk_size: int = 50_000,
    overlap: int = 2_000,
) -> list[ChunkInfo]:
    """Split text into boundary-aware chunks with overlap.

    Args:
        text: Source text to chunk.
        chunk_size: Target chunk size in characters.
        overlap: Overlap between adjacent chunks in characters.

    Returns:
        List of ChunkInfo objects with stable IDs and offsets.
    """
    if not text:
        return []

    text_len = len(text)

    # Single chunk case
    if text_len <= chunk_size:
        return [
            ChunkInfo(
                id="chunk-0001",
                char_start=0,
                char_end=text_len,
                text=text,
                estimated_tokens=_estimate_tokens(text_len),
                heading_context=[],
            )
        ]

    chunks: list[ChunkInfo] = []
    pos = 0
    chunk_num = 1
    # Window for boundary search: last 20% of chunk_size
    window_size = max(1, chunk_size // 5)

    while pos < text_len:
        chunk_end_target = min(pos + chunk_size, text_len)

        if chunk_end_target >= text_len:
            # Last chunk — take everything remaining
            actual_end = text_len
        else:
            # Find best boundary near the target
            window_start = max(pos, chunk_end_target - window_size)
            actual_end = _find_best_boundary(text, chunk_end_target, window_start)

        chunk_text_slice = text[pos:actual_end]
        heading_context = _extract_headings(text[:pos]) if pos > 0 else []

        chunks.append(
            ChunkInfo(
                id=f"chunk-{chunk_num:04d}",
                char_start=pos,
                char_end=actual_end,
                text=chunk_text_slice,
                estimated_tokens=_estimate_tokens(len(chunk_text_slice)),
                heading_context=heading_context,
            )
        )

        chunk_num += 1

        if actual_end >= text_len:
            break

        # Next chunk starts with overlap
        next_start = actual_end - overlap
        if next_start <= pos:
            # Avoid infinite loop: move forward at least 1 char
            next_start = actual_end
        # Snap overlap start to a clean boundary
        if next_start < actual_end and overlap > 0:
            overlap_window_start = max(pos + 1, next_start - overlap // 2)
            snapped = _find_best_boundary(text, next_start, overlap_window_start)
            if snapped > pos and snapped < actual_end:
                next_start = snapped

        pos = next_start

    return chunks
