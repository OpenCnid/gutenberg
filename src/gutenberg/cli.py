"""Gutenberg CLI — ingestion command."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from gutenberg.chunking import chunk_text
from gutenberg.manifest import build_manifest, write_manifest
from gutenberg.prompts import write_prompts
from gutenberg.status import create_status, save_status, load_status, infer_status, reconcile_status, summarize_status
from gutenberg.validation import validate_run
from gutenberg.orchestration import build_plan, format_plan_text, format_plan_json, generate_script, check_synthesis
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
    ingest.add_argument("--context-chars", type=int, default=200, help="Characters of neighboring context per chunk (0 to disable, default: 200).")
    ingest.add_argument("--force", action="store_true", help="Overwrite existing non-empty run directory.")

    status = sub.add_parser("status", help="Show run completion status.")
    status.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    status.add_argument("--json", dest="json_output", action="store_true", help="Output machine-readable JSON.")

    validate = sub.add_parser("validate", help="Validate run directory integrity.")
    validate.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    validate.add_argument("--strict", action="store_true", default=True, help="All checks including hash verification (default).")
    validate.add_argument("--quick", action="store_true", help="Skip hash verification for speed.")
    validate.add_argument("--json", dest="json_output", action="store_true", help="Output machine-readable JSON.")

    orchestrate = sub.add_parser("orchestrate", help="Plan and generate worker commands for a run.")
    orchestrate.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    orchestrate.add_argument("--dry-run", action="store_true", default=True, help="Show plan without executing (default).")
    orchestrate.add_argument("--execute", action="store_true", help="Execute workers (not implemented in V2).")
    orchestrate.add_argument("--synthesis-check", action="store_true", help="Check synthesis readiness.")
    orchestrate.add_argument("--script", action="store_true", help="Generate a shell script for pending workers.")
    orchestrate.add_argument("--skip-failed", action="store_true", help="Skip failed chunks instead of retrying.")
    orchestrate.add_argument("--json", dest="json_output", action="store_true", help="Output machine-readable JSON.")

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
    chunks = chunk_text(source_text, chunk_size=args.chunk_size, overlap=args.overlap, context_chars=args.context_chars)

    # Write chunk files and collect SHA-256 hashes
    chunk_hashes: dict[str, str] = {}
    for chunk in chunks:
        chunk_file = P.chunk_path(run_dir, chunk.id)
        frontmatter_lines = [
            "---",
            f"chunk_id: {chunk.id}",
            f"source: {P.SOURCE_FILENAME}",
            f"char_start: {chunk.char_start}",
            f"char_end: {chunk.char_end}",
            f"estimated_tokens: {chunk.estimated_tokens}",
            f"chunk_index: {chunk.chunk_index}",
            f"chunk_number: {chunk.chunk_number}",
            f"total_chunks: {chunk.total_chunks}",
            f"prev_context: {json.dumps(chunk.prev_context)}",
            f"next_context: {json.dumps(chunk.next_context)}",
        ]
        if chunk.inferred_section is not None:
            frontmatter_lines.append(f"inferred_section: {json.dumps(chunk.inferred_section)}")
        frontmatter_lines.append("---")
        frontmatter = "\n".join(frontmatter_lines) + "\n\n"
        # Title line using the chunk ID
        title_line = f"# Chunk {chunk.id.split('-')[1].lstrip('0') or '0'}\n\n"
        content = frontmatter + title_line + chunk.text
        chunk_hashes[chunk.id] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunk_file.write_text(content, encoding="utf-8")

    # Build and write manifest
    manifest = build_manifest(
        input_path=str(source),
        source_text=source_text,
        chunks=chunks,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        context_chars=args.context_chars,
        title=args.title,
        author=args.author,
        chunk_hashes=chunk_hashes,
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
    # Create status file
    status = create_status(manifest)
    save_status(status, run_dir)

    print()
    print("Next step: Open the orchestrator prompt and follow the manual workflow:")
    print(f"  {P.orchestrator_prompt_path(run_dir)}")

    return 0


def _run_status(args: argparse.Namespace) -> int:
    """Execute the status subcommand."""
    run_dir = Path(args.run_dir)

    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        print(f"Error: No manifest.json in {run_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    # Load status or infer from filesystem, then reconcile with reality
    status = load_status(run_dir)
    if status is None:
        status = infer_status(manifest, run_dir)
    else:
        status = reconcile_status(status, manifest, run_dir)

    summary = summarize_status(status)

    if args.json_output:
        json.dump(summary, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0 if summary["run_state"] == "complete" else 1

    # Human-readable output
    print(f"Run: {run_dir.name}")
    print(f"State: {summary['run_state']}")
    print()

    for cid, entry in status["chunks"].items():
        state = entry["state"]
        print(f"  {cid}: {state}")

    print()
    parts = []
    if summary["done"]:
        parts.append(f"{summary['done']} done")
    if summary["pending"]:
        parts.append(f"{summary['pending']} pending")
    if summary["running"]:
        parts.append(f"{summary['running']} running")
    if summary["failed"]:
        parts.append(f"{summary['failed']} failed")
    if summary["missing"]:
        parts.append(f"{summary['missing']} missing")
    print(f"  {', '.join(parts)} of {summary['total']} total")

    return 0 if summary["run_state"] == "complete" else 1


def _run_validate(args: argparse.Namespace) -> int:
    """Execute the validate subcommand."""
    run_dir = Path(args.run_dir)

    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    strict = not args.quick
    checks = validate_run(run_dir, strict=strict)

    if args.json_output:
        json.dump(checks, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        for c in checks:
            mark = "\u2713" if c["passed"] else "\u2717"
            print(f"  {mark} {c['check']}: {c['detail']}")
        print()
        passed = sum(1 for c in checks if c["passed"])
        failed = sum(1 for c in checks if not c["passed"])
        print(f"  {passed} passed, {failed} failed")

    all_passed = all(c["passed"] for c in checks)
    return 0 if all_passed else 1


def _run_orchestrate(args: argparse.Namespace) -> int:
    """Execute the orchestrate subcommand."""
    run_dir = Path(args.run_dir)

    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        print(f"Error: No manifest.json in {run_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    # --execute is not implemented in V2
    if args.execute:
        print("Warning: --execute is not implemented in V2. "
              "Orchestration generates commands and scripts only.", file=sys.stderr)
        return 1

    # Load or infer status, then reconcile with reality
    status = load_status(run_dir)
    if status is None:
        status = infer_status(manifest, run_dir)
    else:
        status = reconcile_status(status, manifest, run_dir)

    plan = build_plan(manifest, status, skip_failed=args.skip_failed)

    if args.synthesis_check:
        synthesis = check_synthesis(plan, manifest, run_dir)
        if args.json_output:
            json.dump(synthesis, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            if synthesis["ready"]:
                print("Synthesis: READY")
                print(f"  Prompt: {synthesis['synthesis_prompt']}")
                print(f"  Output: {synthesis['synthesis_output']}")
            else:
                print("Synthesis: NOT READY")
                for b in synthesis["blockers"]:
                    print(f"  Blocker: {b}")
        return 0 if synthesis["ready"] else 1

    if args.script:
        script = generate_script(plan, run_dir)
        if args.json_output:
            json.dump({"script": script}, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            print(script)
        return 0

    # Default: dry-run plan
    if args.json_output:
        json.dump(format_plan_json(plan, run_dir), sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        print(format_plan_text(plan, run_dir))

    return 0


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    handlers = {
        "ingest": _run_ingest,
        "status": _run_status,
        "validate": _run_validate,
        "orchestrate": _run_orchestrate,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    rc = handler(args)
    if rc != 0:
        sys.exit(rc)
