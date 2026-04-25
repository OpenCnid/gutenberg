# Boundary-Aware Chunking

Chunking should preserve reading context as much as possible while staying near the requested chunk size.

The default target is `50_000` characters per chunk with `2_000` characters of overlap between adjacent chunks.

## Boundary Preference

When choosing a chunk end, prefer boundaries in this order:

1. Markdown heading boundary.
2. Blank-line paragraph boundary.
3. Sentence-ish punctuation boundary.
4. Whitespace boundary.
5. Hard character boundary as a last resort.

The implementation does not need NLP-quality sentence detection in V1. Simple heuristics are fine if behavior is deterministic and documented.

## Overlap Behavior

- Adjacent chunks should overlap by approximately the configured overlap size.
- Overlap should also prefer clean boundaries when reasonable.
- Overlap exists to preserve context, not to hit an exact byte count.
- The manifest must record actual character offsets for every chunk.

## Chunk Markdown Format

Each chunk file should be markdown with lightweight YAML-style frontmatter:

```md
---
chunk_id: chunk-0001
source: source.txt
char_start: 0
char_end: 50000
estimated_tokens: 12000
---

# Chunk 0001

<chunk text>
```

Rules:

- `chunk_id` must be stable and zero-padded: `chunk-0001`, `chunk-0002`, etc.
- `char_start` and `char_end` refer to offsets in `source.txt`.
- `estimated_tokens` can be an approximation. V1 may use `ceil(chars / 4)` or another documented heuristic.
- The body should contain only the relevant source text plus a simple title/header.

## Edge Cases

- Very small files should produce one chunk.
- Files smaller than `chunk-size` should not create unnecessary overlaps.
- Files with no paragraphs/headings should still chunk successfully.
- Non-ASCII text should preserve characters correctly.
- The algorithm should avoid infinite loops when overlap is large or boundaries are sparse.

## Acceptance Criteria

- Default chunking uses `50_000` character target and `2_000` overlap.
- Chunk boundaries prefer headings/paragraphs over hard cuts when those boundaries are near the target.
- Each chunk has frontmatter with stable id, offsets, source path, and estimated tokens.
- The manifest offsets match the chunk frontmatter.
- Reconstructing chunks with overlap removed should not reveal missing source spans.
- Chunking is deterministic for the same input and options.
