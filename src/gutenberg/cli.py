"""Gutenberg CLI — ingestion command."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from gutenberg.chunking import chunk_text
from gutenberg.manifest import build_manifest, write_manifest
from gutenberg.prompts import write_prompts
from gutenberg import paths as P


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gutenberg",
        description="Ingest long texts into knowledge synthesis run directories.",
    )
    sub = parser.add_subparsers(dest="command")

    ingest = sub.add_parser("ingest", help="Ingest a source file into a run directory.")
    ingest.add_argument("source", help="Path to the source text/markdown file.")
    ingest.add_argument("--out", required=True, help="Output run directory path.")
    ingest.add_argument("--chunk-size", type=int, default=50_000, help="Target chunk size in characters (default: 50000).")
    ingest.add_argument("--overlap", type=int, default=2_000, help="Overlap between chunks in characters (default: 2000).")
    ingest.add_argument("--title", default=None, help="Human-readable title for the source.")
    ingest.add_argument("--author", default=None, help="Author metadata.")
    ingest.add_argument("--force", action="store_true", help="Overwrite existing non-empty run directory.")

    return parser


def _validate_args(args: argparse.Namespace) -> list[str]:
    """Validate parsed arguments. Returns list of error messages."""
    errors: list[str] = []

    if args.chunk_size <= 0:
        errors.append(f"--chunk-size must be positive, got {args.chunk_size}")
    if args.overlap < 0:
        errors.append(f"--overlap must be zero or positive, got {args.overlap}")
    if args.overlap >= args.chunk_size:
        errors.append(f"--overlap ({args.overlap}) must be smaller than --chunk-size ({args.chunk_size})")

    source = Path(args.source)
    if not source.exists():
        errors.append(f"Source file not found: {args.source}")
    elif not source.is_file():
        errors.append(f"Source path is not a file: {args.source}")

    return errors


def _run_ingest(args: argparse.Namespace) -> int:
    """Execute the ingest pipeline."""
    # Validate
    errors = _validate_args(args)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    source = Path(args.source)
    run_dir = Path(args.out)

    # Check output directory
    if run_dir.exists() and any(run_dir.iterdir()):
        if not args.force:
            print(
                f"Error: Output directory is not empty: {args.out}\n"
                f"Use --force to overwrite.",
                file=sys.stderr,
            )
            return 1
        # Force mode: remove existing contents
        shutil.rmtree(run_dir)

    # Create directory structure
    run_dir.mkdir(parents=True, exist_ok=True)
    P.chunks_dir(run_dir).mkdir(exist_ok=True)
    P.prompts_dir(run_dir).mkdir(exist_ok=True)
    P.results_dir(run_dir).mkdir(exist_ok=True)

    # Copy source
    source_text = source.read_text(encoding="utf-8")
    P.source_path(run_dir).write_text(source_text, encoding="utf-8")

    # Chunk
    chunks = chunk_text(source_text, chunk_size=args.chunk_size, overlap=args.overlap)

    # Write chunk files
    for chunk in chunks:
        chunk_file = P.chunk_path(run_dir, chunk.id)
        frontmatter = (
            f"---\n"
            f"chunk_id: {chunk.id}\n"
            f"source: {P.SOURCE_FILENAME}\n"
            f"char_start: {chunk.char_start}\n"
            f"char_end: {chunk.char_end}\n"
            f"estimated_tokens: {chunk.estimated_tokens}\n"
            f"---\n\n"
        )
        # Title line using the chunk ID
        title_line = f"# Chunk {chunk.id.split('-')[1].lstrip('0') or '0'}\n\n"
        chunk_file.write_text(frontmatter + title_line + chunk.text, encoding="utf-8")

    # Build and write manifest
    manifest = build_manifest(
        input_path=str(source),
        source_text=source_text,
        chunks=chunks,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        title=args.title,
        author=args.author,
    )
    write_manifest(manifest, run_dir)

    # Write prompts
    write_prompts(manifest, run_dir)

    # Create results/.gitkeep
    (P.results_dir(run_dir) / ".gitkeep").touch()

    # Print summary
    print(f"Gutenberg run created: {run_dir}")
    print(f"  Source: {source}")
    print(f"  Chunks: {len(chunks)}")
    print(f"  Chunk size: {args.chunk_size} chars")
    print(f"  Overlap: {args.overlap} chars")
    print(f"  Manifest: {P.manifest_path(run_dir)}")
    print()
    print("Next step: Open the orchestrator prompt and follow the manual workflow:")
    print(f"  {P.orchestrator_prompt_path(run_dir)}")

    return 0


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "ingest":
        rc = _run_ingest(args)
        if rc != 0:
            sys.exit(rc)
