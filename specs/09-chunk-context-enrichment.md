# Spec 09: Chunk Context Enrichment

The chunk context system adds positional and structural metadata to chunks for texts without markdown headings.

## Problem

V1's chunking tracks heading context for markdown files with `#`-style headings, but plain prose (like Project Gutenberg texts) has no headings. Workers receive chunks with no positional context — they don't know where they are in the text, what comes before or after, or how the text is structured. This makes worker analysis less coherent and synthesis harder.

V1 worker prompts also lack chunk position information (e.g., "chunk 5 of 9"), forcing workers to analyze in isolation without knowing their place in the overall text.

## Requirements

### Chunk Position Metadata

- Every chunk gets explicit position metadata: `chunk_index` (0-based), `chunk_number` (1-based), `total_chunks`.
- Position metadata is included in chunk YAML frontmatter.
- Position metadata is included in `manifest.json` per-chunk entries.
- Worker prompts include "Chunk X of N" prominently.

### Neighboring Context

- Each chunk's frontmatter includes a brief context summary of adjacent chunks.
- `prev_context`: last 200 characters of the previous chunk (or "Start of text" for chunk 0).
- `next_context`: first 200 characters of the next chunk (or "End of text" for the last chunk).
- Context length is configurable via `--context-chars` (default 200).
- This gives workers awareness of what surrounds their chunk without duplicating full content.

### Prose Structure Detection

- For texts without markdown headings, attempt lightweight structural detection:
  - Chapter markers (e.g., "CHAPTER I", "Chapter 1", "PART ONE").
  - Letter/section markers (e.g., "Letter 1", "Walton, in continuation").
  - Blank-line-separated sections.
- Detected structure is recorded as `inferred_section` in chunk frontmatter.
- This is best-effort — if no structure is detected, the field is omitted (not empty string).
- Detection patterns should be conservative: prefer missing over wrong.

### Prompt Template Updates

- Worker prompt template includes chunk position: "You are analyzing chunk {chunk_number} of {total_chunks}."
- Worker prompt template includes neighboring context when available.
- Synthesis prompt template includes total chunk count and lists which chunks have results.

### Compatibility

- V1 heading-based context is preserved unchanged for markdown files with headings.
- New metadata fields are additive — they do not replace existing frontmatter fields.
- V1 manifests without the new fields are still valid (new fields are optional for validation).

## Acceptance Criteria

- Chunk frontmatter includes `chunk_index`, `chunk_number`, `total_chunks` for all chunks.
- Chunk frontmatter includes `prev_context` and `next_context` with correct content from neighbors.
- Plain prose text with "CHAPTER" markers gets `inferred_section` populated.
- Plain prose text with no detectable structure omits `inferred_section` (no empty field).
- Worker prompt includes "chunk X of N" text.
- Synthesis prompt lists chunk count and result availability.
- Markdown files with headings still get heading context as before (no regression).
- `--context-chars 0` disables neighboring context.
