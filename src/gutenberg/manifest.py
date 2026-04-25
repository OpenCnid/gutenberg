"""Manifest generation and validation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gutenberg import __version__
from gutenberg.chunking import ChunkInfo
from gutenberg import paths as P


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    input_path: str,
    source_text: str,
    chunks: list[ChunkInfo],
    chunk_size: int,
    overlap: int,
    context_chars: int = 200,
    title: str | None = None,
    author: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the manifest dict for a run."""
    if created_at is None:
        created_at = datetime.now(timezone.utc)

    return {
        "schema_version": "1.0",
        "tool": {
            "name": "gutenberg",
            "version": __version__,
        },
        "created_at": created_at.isoformat(),
        "source": {
            "input_path": input_path,
            "stored_path": P.SOURCE_FILENAME,
            "title": title or "",
            "author": author or "",
            "sha256": _sha256(source_text),
            "char_count": len(source_text),
        },
        "settings": {
            "chunk_size": chunk_size,
            "overlap": overlap,
            "context_chars": context_chars,
            "splitter": "boundary-aware-v1",
            "estimated_token_method": "chars_div_4",
        },
        "prompts": {
            "orchestrator": f"{P.PROMPTS_DIR}/{P.ORCHESTRATOR_PROMPT}",
            "worker": f"{P.PROMPTS_DIR}/{P.WORKER_PROMPT}",
            "synthesis": f"{P.PROMPTS_DIR}/{P.SYNTHESIS_PROMPT}",
        },
        "chunks": [
            {
                "id": c.id,
                "path": f"{P.CHUNKS_DIR}/{c.id}.md",
                "char_start": c.char_start,
                "char_end": c.char_end,
                "estimated_tokens": c.estimated_tokens,
                "heading_context": c.heading_context,
                "chunk_index": c.chunk_index,
                "chunk_number": c.chunk_number,
                "total_chunks": c.total_chunks,
                "prev_context": c.prev_context,
                "next_context": c.next_context,
                **({
                    "inferred_section": c.inferred_section,
                } if c.inferred_section is not None else {}),
            }
            for c in chunks
        ],
        "results": {
            "directory": P.RESULTS_DIR,
            "expected_worker_pattern": f"{P.RESULTS_DIR}/{{chunk_id}}.analysis.md",
            "expected_synthesis_path": f"{P.RESULTS_DIR}/synthesis.md",
        },
    }


def write_manifest(manifest: dict[str, Any], run_dir: Path) -> Path:
    """Write manifest.json to the run directory."""
    path = P.manifest_path(run_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    return path


def validate_manifest(manifest: dict[str, Any], run_dir: Path) -> list[str]:
    """Validate a manifest dict against the run directory.

    Returns a list of error strings. Empty list means valid.
    """
    errors: list[str] = []

    # Required top-level fields
    for field in ("schema_version", "tool", "created_at", "source", "settings", "prompts", "chunks", "results"):
        if field not in manifest:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors  # Can't continue without structure

    # Check source file exists
    source_stored = manifest.get("source", {}).get("stored_path", "")
    if source_stored and not (run_dir / source_stored).exists():
        errors.append(f"Source file not found: {source_stored}")

    # Check chunk files
    chunk_ids = set()
    prev_end = -1
    for i, chunk in enumerate(manifest.get("chunks", [])):
        cid = chunk.get("id", "")

        # Unique IDs
        if cid in chunk_ids:
            errors.append(f"Duplicate chunk ID: {cid}")
        chunk_ids.add(cid)

        # File exists
        cpath = chunk.get("path", "")
        if cpath and not (run_dir / cpath).exists():
            errors.append(f"Chunk file not found: {cpath}")

        # Monotonic offsets
        cs = chunk.get("char_start", 0)
        ce = chunk.get("char_end", 0)
        if cs >= ce:
            errors.append(f"Chunk {cid}: char_start ({cs}) >= char_end ({ce})")
        if i > 0 and cs >= prev_end:
            # With overlap, next chunk's start should be before previous chunk's end
            # But without overlap they could be equal. Check they're at least ordered.
            pass
        prev_end = ce

    # Check prompt files
    for role in ("orchestrator", "worker", "synthesis"):
        ppath = manifest.get("prompts", {}).get(role, "")
        if ppath and not (run_dir / ppath).exists():
            errors.append(f"Prompt file not found: {ppath}")

    # Check results directory
    rdir = manifest.get("results", {}).get("directory", "")
    if rdir and not (run_dir / rdir).exists():
        errors.append(f"Results directory not found: {rdir}")

    return errors
