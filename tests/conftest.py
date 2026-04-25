"""Shared fixtures for Gutenberg tests."""

import pytest


@pytest.fixture
def short_text():
    """A short text that fits in one chunk."""
    return "This is a short text.\n\nIt has two paragraphs.\n"


@pytest.fixture
def medium_text():
    """A text that produces multiple chunks at small chunk sizes."""
    paragraphs = []
    for i in range(50):
        paragraphs.append(
            f"## Section {i + 1}\n\n"
            f"This is paragraph {i + 1} of the test document. "
            f"It contains some meaningful content that helps test boundary-aware chunking. "
            f"The paragraph is long enough to be useful but not so long that it dominates a chunk. "
            f"Each section has a heading so we can test heading boundary detection.\n"
        )
    return "\n".join(paragraphs)


@pytest.fixture
def heading_text():
    """Text with nested headings."""
    return (
        "# Chapter 1\n\n"
        "Introduction text.\n\n"
        "## Section 1.1\n\n"
        "Details about section 1.1.\n\n"
        "### Subsection 1.1.1\n\n"
        "More details.\n\n"
        "## Section 1.2\n\n"
        "Details about section 1.2.\n\n"
        "# Chapter 2\n\n"
        "Second chapter content.\n\n"
        "## Section 2.1\n\n"
        "Details about section 2.1.\n"
    )


@pytest.fixture
def no_heading_text():
    """Plain text with no markdown headings."""
    sentences = [f"Sentence number {i + 1} in the document." for i in range(100)]
    return " ".join(sentences)


@pytest.fixture
def unicode_text():
    """Text with non-ASCII characters."""
    return (
        "# Kapitel Eins\n\n"
        "Dies ist ein deutscher Text mit Umlauten: ä, ö, ü, ß.\n\n"
        "## 日本語セクション\n\n"
        "日本語のテキストも正しく処理されるべきです。\n\n"
        "## Sección Española\n\n"
        "El texto en español también debería funcionar correctamente.\n"
    )


@pytest.fixture
def source_file(tmp_path, medium_text):
    """Write medium_text to a file and return its path."""
    p = tmp_path / "source.txt"
    p.write_text(medium_text, encoding="utf-8")
    return p
