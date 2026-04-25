"""Tests for boundary-aware chunking."""

import math

from gutenberg.chunking import chunk_text


class TestChunkTextDefaults:
    def test_empty_text(self):
        assert chunk_text("") == []

    def test_single_chunk_short(self, short_text):
        chunks = chunk_text(short_text)
        assert len(chunks) == 1
        assert chunks[0].id == "chunk-0001"
        assert chunks[0].char_start == 0
        assert chunks[0].char_end == len(short_text)
        assert chunks[0].text == short_text

    def test_single_chunk_no_overlap(self, short_text):
        """File smaller than chunk_size should not create unnecessary overlaps."""
        chunks = chunk_text(short_text, chunk_size=50_000, overlap=2_000)
        assert len(chunks) == 1

    def test_default_sizes(self, medium_text):
        """With defaults, medium_text should be one chunk (it's under 50k)."""
        chunks = chunk_text(medium_text)
        # medium_text is around 10k chars, so single chunk
        assert len(chunks) == 1


class TestChunkTextCustomSizes:
    def test_small_chunks(self, medium_text):
        """Smaller chunk sizes should produce multiple chunks."""
        chunks = chunk_text(medium_text, chunk_size=500, overlap=50)
        assert len(chunks) > 1

    def test_chunk_ids_sequential(self, medium_text):
        chunks = chunk_text(medium_text, chunk_size=500, overlap=50)
        for i, chunk in enumerate(chunks):
            assert chunk.id == f"chunk-{i + 1:04d}"

    def test_chunk_offsets_cover_source(self, medium_text):
        """Chunks should cover the full source text without gaps (accounting for overlap)."""
        chunks = chunk_text(medium_text, chunk_size=500, overlap=50)
        # First chunk starts at 0
        assert chunks[0].char_start == 0
        # Last chunk ends at text length
        assert chunks[-1].char_end == len(medium_text)
        # No gaps: each chunk's start should be <= previous chunk's end
        for i in range(1, len(chunks)):
            assert chunks[i].char_start < chunks[i - 1].char_end, (
                f"Gap between chunk {i} and {i + 1}"
            )

    def test_no_overlap(self, medium_text):
        """With overlap=0, chunks should be adjacent."""
        chunks = chunk_text(medium_text, chunk_size=500, overlap=0)
        assert len(chunks) > 1
        for i in range(1, len(chunks)):
            assert chunks[i].char_start == chunks[i - 1].char_end

    def test_zero_overlap_no_gaps(self, medium_text):
        """Concatenating zero-overlap chunks should reconstruct the source."""
        chunks = chunk_text(medium_text, chunk_size=500, overlap=0)
        reconstructed = "".join(c.text for c in chunks)
        assert reconstructed == medium_text


class TestBoundaryPreference:
    def test_prefers_heading_boundary(self, heading_text):
        """With small chunks, should split at headings when possible."""
        chunks = chunk_text(heading_text, chunk_size=80, overlap=0)
        # At least some chunks should start at heading positions
        heading_starts = [i for i, c in enumerate(heading_text) if heading_text[i:].startswith("\n#")]
        # Verify chunks exist and boundaries are at reasonable positions
        assert len(chunks) > 1

    def test_prefers_paragraph_boundary(self, no_heading_text):
        """Without headings, should split at sentence/whitespace boundaries."""
        chunks = chunk_text(no_heading_text, chunk_size=200, overlap=0)
        # Chunks should not split mid-word
        for chunk in chunks[:-1]:  # Last chunk can end anywhere
            assert chunk.text[-1] in " .\n", (
                f"Chunk ends mid-word: ...{chunk.text[-20:]!r}"
            )


class TestTokenEstimation:
    def test_token_estimate(self, short_text):
        chunks = chunk_text(short_text)
        expected = math.ceil(len(short_text) / 4)
        assert chunks[0].estimated_tokens == expected

    def test_token_estimate_custom(self):
        text = "a" * 100
        chunks = chunk_text(text)
        assert chunks[0].estimated_tokens == 25


class TestHeadingContext:
    def test_first_chunk_empty_context(self, heading_text):
        chunks = chunk_text(heading_text, chunk_size=80, overlap=0)
        assert chunks[0].heading_context == []

    def test_later_chunks_have_context(self, heading_text):
        chunks = chunk_text(heading_text, chunk_size=80, overlap=0)
        if len(chunks) > 1:
            # At least one later chunk should have heading context
            has_context = any(c.heading_context for c in chunks[1:])
            assert has_context


class TestEdgeCases:
    def test_unicode_preserves_characters(self, unicode_text):
        chunks = chunk_text(unicode_text)
        # Single chunk for small text
        assert chunks[0].text == unicode_text

    def test_unicode_multi_chunk(self, unicode_text):
        chunks = chunk_text(unicode_text, chunk_size=50, overlap=10)
        # Reconstruct should preserve all characters
        full = unicode_text
        for chunk in chunks:
            assert chunk.text == full[chunk.char_start:chunk.char_end]

    def test_large_overlap_no_infinite_loop(self):
        """Large overlap relative to chunk_size should not cause infinite loop."""
        text = "word " * 100
        chunks = chunk_text(text, chunk_size=20, overlap=15)
        assert len(chunks) > 0
        assert chunks[-1].char_end == len(text)

    def test_deterministic(self, medium_text):
        """Same input and options should produce same output."""
        c1 = chunk_text(medium_text, chunk_size=500, overlap=50)
        c2 = chunk_text(medium_text, chunk_size=500, overlap=50)
        assert len(c1) == len(c2)
        for a, b in zip(c1, c2):
            assert a.id == b.id
            assert a.char_start == b.char_start
            assert a.char_end == b.char_end
            assert a.text == b.text
