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
from gutenberg.status import create_status, save_status, load_status, infer_status, reconcile_status, summarize_status, summarize_failures, full_status_json
from gutenberg.validation import validate_run
from gutenberg.orchestration import build_plan, format_plan_text, format_plan_json, generate_script, check_synthesis
from gutenberg.tasks import materialize_tasks, check_staleness
from gutenberg.lifecycle import mark_chunk, retry_chunks, skip_chunk
from gutenberg.executor import (
    load_executor_config,
    validate_executor_config,
    create_executor,
    execute_workers,
)
from gutenberg.synthesis import (
    check_synthesis_readiness,
    execute_synthesis,
)
from gutenberg.reporting import (
    append_event,
    build_report,
    format_report_markdown,
    format_report_json,
    write_reports,
)
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
    status.add_argument("--failures", action="store_true", help="Show only failed/skipped/missing chunks.")
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
    orchestrate.add_argument("--executor", default=None, help="Executor type or profile name.")
    orchestrate.add_argument("--executor-config", default=None, help="Path to executor config JSON.")
    orchestrate.add_argument("--concurrency", type=int, default=1, help="Max workers to run concurrently (default: 1).")
    orchestrate.add_argument("--timeout-seconds", type=int, default=1800, help="Per-worker timeout in seconds (default: 1800).")
    orchestrate.add_argument("--retry-failed", action="store_true", help="Include failed chunks in execution queue.")
    orchestrate.add_argument("--only", action="append", default=None, help="Only execute specific chunk IDs (repeatable).")
    orchestrate.add_argument("--log-max-bytes", type=int, default=None, help="Per-attempt log size cap in bytes (default: 524288).")
    orchestrate.add_argument("--json", dest="json_output", action="store_true", help="Output machine-readable JSON.")

    report = sub.add_parser("report", help="Generate run report.")
    report.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    report.add_argument("--json", dest="json_output", action="store_true", help="Output machine-readable JSON.")
    report.add_argument("--markdown", action="store_true", help="Output markdown report.")
    report.add_argument("--write", action="store_true", help="Write reports to reports/ directory.")
    report.add_argument("--include-validation", action="store_true", help="Include validation results.")

    synthesize = sub.add_parser("synthesize", help="Run synthesis over worker results.")
    synthesize.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    synthesize.add_argument("--execute", action="store_true", help="Launch synthesis executor.")
    synthesize.add_argument("--partial", action="store_true", help="Allow synthesis with missing chunks.")
    synthesize.add_argument("--force", action="store_true", help="Overwrite existing synthesis output.")
    synthesize.add_argument("--executor", default=None, help="Executor type or profile name.")
    synthesize.add_argument("--executor-config", default=None, help="Path to executor config JSON.")
    synthesize.add_argument("--timeout-seconds", type=int, default=1800, help="Synthesis timeout (default: 1800).")
    synthesize.add_argument("--log-max-bytes", type=int, default=None, help="Per-attempt log size cap in bytes (default: 524288).")
    synthesize.add_argument("--json", dest="json_output", action="store_true", help="Output machine-readable JSON.")

    execute = sub.add_parser("execute", help="Execute workers (alias for orchestrate --execute).")
    execute.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    execute.add_argument("--executor", default=None, help="Executor type or profile name.")
    execute.add_argument("--executor-config", default=None, help="Path to executor config JSON.")
    execute.add_argument("--concurrency", type=int, default=1, help="Max workers to run concurrently (default: 1).")
    execute.add_argument("--timeout-seconds", type=int, default=1800, help="Per-worker timeout in seconds (default: 1800).")
    execute.add_argument("--retry-failed", action="store_true", help="Include failed chunks in execution queue.")
    execute.add_argument("--skip-failed", action="store_true", help="Skip failed chunks.")
    execute.add_argument("--only", action="append", default=None, help="Only execute specific chunk IDs (repeatable).")
    execute.add_argument("--log-max-bytes", type=int, default=None, help="Per-attempt log size cap in bytes (default: 524288).")
    execute.add_argument("--json", dest="json_output", action="store_true", help="Output machine-readable JSON.")

    mark = sub.add_parser("mark", help="Manually set a chunk's state.")
    mark.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    mark.add_argument("chunk_id", metavar="chunk-id", help="Chunk ID to mark.")
    mark.add_argument("state", help="New state (pending, failed, skipped, missing, done).")
    mark.add_argument("--reason", default=None, help="Reason (required for failed/skipped).")

    retry = sub.add_parser("retry", help="Reset failed/missing/skipped chunks to pending.")
    retry.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    retry.add_argument("--failed", action="store_true", help="Reset all failed/missing chunks.")
    retry.add_argument("--chunk", dest="chunk_ids", action="append", default=None, help="Specific chunk ID to retry (repeatable).")
    retry.add_argument("--force", action="store_true", help="Override max_attempts limit.")

    skip = sub.add_parser("skip", help="Mark a chunk as skipped.")
    skip.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    skip.add_argument("chunk_id", metavar="chunk-id", help="Chunk ID to skip.")
    skip.add_argument("--reason", required=True, help="Reason for skipping.")

    tasks = sub.add_parser("tasks", help="Materialize per-chunk task files.")
    tasks.add_argument("run_dir", metavar="run-dir", help="Path to the run directory.")
    tasks.add_argument("--refresh", action="store_true", help="Regenerate all task files.")
    tasks.add_argument("--dry-run", action="store_true", help="Show plan without writing files.")
    tasks.add_argument("--json", dest="json_output", action="store_true", help="Output machine-readable JSON.")

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

    if args.failures:
        problems = summarize_failures(status)
        if args.json_output:
            json.dump(problems, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            if not problems:
                print("No failures, skips, or missing chunks.")
            else:
                for p in problems:
                    line = f"  {p['chunk_id']}: {p['state']}"
                    if "reason" in p:
                        line += f" — {p['reason']}"
                    elif "last_error" in p:
                        le = p["last_error"]
                        line += f" — {le.get('message', le.get('code', ''))}"
                    if "attempt_count" in p:
                        line += f" ({p['attempt_count']} attempts)"
                    print(line)
        return 0 if not problems else 1

    if args.json_output:
        detail = full_status_json(status)
        json.dump(detail, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0 if detail["run_state"] == "complete" else 1

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
    if summary.get("skipped"):
        parts.append(f"{summary['skipped']} skipped")
    print(f"  {', '.join(parts)} of {summary['total']} total")

    # Show warnings (e.g. unknown chunks in status)
    warnings = status.get("_warnings", [])
    if warnings:
        print()
        for w in warnings:
            print(f"  Warning: {w}")

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

    if args.execute:
        return _run_execute_impl(args, run_dir, manifest)

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


def _run_report(args: argparse.Namespace) -> int:
    """Execute the report subcommand."""
    run_dir = Path(args.run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        print(f"Error: No manifest.json in {run_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    status = load_status(run_dir)
    if status is None:
        status = infer_status(manifest, run_dir)
    else:
        status = reconcile_status(status, manifest, run_dir)

    report = build_report(manifest, status, run_dir)

    if args.include_validation:
        from gutenberg.validation import validate_run
        checks = validate_run(run_dir, strict=True)
        report["validation"] = checks

    if args.write:
        md_path, json_path = write_reports(report, run_dir)
        print(f"Reports written:")
        print(f"  Markdown: {md_path}")
        print(f"  JSON: {json_path}")
        return 0

    if args.json_output:
        json.dump(format_report_json(report), sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        print(format_report_markdown(report))

    return 0


def _run_synthesize(args: argparse.Namespace) -> int:
    """Execute the synthesize subcommand."""
    run_dir = Path(args.run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        print(f"Error: No manifest.json in {run_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    status = load_status(run_dir)
    if status is None:
        status = infer_status(manifest, run_dir)
    else:
        status = reconcile_status(status, manifest, run_dir)

    if not args.execute:
        # Dry-run: readiness check only
        readiness = check_synthesis_readiness(manifest, status, run_dir)

        if args.json_output:
            json.dump(readiness, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            if readiness["ready"]:
                print("Synthesis: READY")
                print(f"  Available results: {readiness['available_results']} of {readiness['input_chunks']}")
            else:
                print("Synthesis: NOT READY")
                for b in readiness["blockers"]:
                    print(f"  Blocker: {b}")
        return 0 if readiness["ready"] else 1

    # Execute synthesis
    cli_overrides: dict[str, Any] = {}
    if args.executor:
        cli_overrides["type"] = args.executor
    if args.timeout_seconds:
        cli_overrides["timeout_seconds"] = args.timeout_seconds

    config = load_executor_config(
        config_path=getattr(args, "executor_config", None),
        cli_overrides=cli_overrides,
    )

    exec_type = config.get("type", "command")
    if exec_type != "manual" and "command" not in config:
        print("Error: No executor command configured.", file=sys.stderr)
        return 1

    errors = validate_executor_config(config)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    executor = create_executor(config)

    result = execute_synthesis(
        manifest=manifest,
        status=status,
        run_dir=run_dir,
        executor=executor,
        partial=args.partial,
        force=args.force,
        timeout=config.get("timeout_seconds", 1800),
        log_max_bytes=getattr(args, "log_max_bytes", None),
    )

    if args.json_output:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        if result["success"]:
            state = result.get("state", "done")
            print(f"Synthesis {state}: {result.get('result_path', '')}")
            if result.get("partial"):
                print(f"  Partial: {result['available_results']} of {result['input_chunks']} chunks")
        else:
            print(f"Synthesis failed: {result.get('reason', 'unknown')}")
            for b in result.get("blockers", []):
                print(f"  Blocker: {b}")

    return 0 if result["success"] else 1


def _run_execute(args: argparse.Namespace) -> int:
    """Execute the execute subcommand (alias for orchestrate --execute)."""
    run_dir = Path(args.run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        print(f"Error: No manifest.json in {run_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    return _run_execute_impl(args, run_dir, manifest)


def _run_execute_impl(args: argparse.Namespace, run_dir: Path, manifest: dict) -> int:
    """Shared execution logic for orchestrate --execute and execute."""
    # Build executor config
    cli_overrides: dict[str, Any] = {}
    if getattr(args, "executor", None):
        cli_overrides["type"] = args.executor
    if getattr(args, "concurrency", None):
        cli_overrides["concurrency"] = args.concurrency
    if getattr(args, "timeout_seconds", None):
        cli_overrides["timeout_seconds"] = args.timeout_seconds

    config = load_executor_config(
        config_path=getattr(args, "executor_config", None),
        cli_overrides=cli_overrides,
    )

    # Ensure there's a command for non-manual executors
    exec_type = config.get("type", "command")
    if exec_type != "manual" and "command" not in config:
        print("Error: No executor command configured. "
              "Use --executor-config or provide --executor manual.",
              file=sys.stderr)
        return 1

    errors = validate_executor_config(config)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    executor = create_executor(config)

    status = load_status(run_dir)
    if status is None:
        status = infer_status(manifest, run_dir)

    result = execute_workers(
        manifest=manifest,
        status=status,
        run_dir=run_dir,
        executor=executor,
        concurrency=config.get("concurrency", 1),
        only=getattr(args, "only", None),
        retry_failed=getattr(args, "retry_failed", False),
        timeout=config.get("timeout_seconds", 1800),
        executor_config=config,
        log_max_bytes=getattr(args, "log_max_bytes", None),
    )

    if getattr(args, "json_output", False):
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        print(f"Execution complete:")
        print(f"  Launched: {result['launched']}")
        print(f"  Succeeded: {result['succeeded']}")
        print(f"  Failed: {result['failed']}")
        if result.get("interrupted"):
            print(f"  Interrupted: yes")

    return 1 if result["failed"] > 0 else 0


def _run_mark(args: argparse.Namespace) -> int:
    """Execute the mark subcommand."""
    run_dir = Path(args.run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        print(f"Error: No manifest.json in {run_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    status = load_status(run_dir)
    if status is None:
        status = infer_status(manifest, run_dir)

    try:
        mark_chunk(status, args.chunk_id, args.state, reason=args.reason, run_dir=run_dir)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    save_status(status, run_dir)
    append_event(run_dir, {
        "event": "chunk_marked",
        "chunk_id": args.chunk_id,
        "state": args.state,
        "reason": args.reason,
    })
    print(f"Marked {args.chunk_id} as {args.state}.")
    return 0


def _run_retry(args: argparse.Namespace) -> int:
    """Execute the retry subcommand."""
    run_dir = Path(args.run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        print(f"Error: No manifest.json in {run_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    status = load_status(run_dir)
    if status is None:
        status = infer_status(manifest, run_dir)

    if not args.failed and not args.chunk_ids:
        print("Error: Specify --failed or --chunk <chunk-id>.", file=sys.stderr)
        return 1

    reset = retry_chunks(
        status, manifest,
        which="failed",
        chunk_ids=args.chunk_ids,
        force=args.force,
    )

    if not reset:
        print("No chunks eligible for retry.")
    else:
        save_status(status, run_dir)
        for cid in reset:
            append_event(run_dir, {
                "event": "chunk_retried",
                "chunk_id": cid,
            })
        print(f"Reset {len(reset)} chunk(s) to pending: {', '.join(reset)}")

    return 0


def _run_skip(args: argparse.Namespace) -> int:
    """Execute the skip subcommand."""
    run_dir = Path(args.run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        print(f"Error: No manifest.json in {run_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    status = load_status(run_dir)
    if status is None:
        status = infer_status(manifest, run_dir)

    try:
        skip_chunk(status, args.chunk_id, args.reason)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    save_status(status, run_dir)
    append_event(run_dir, {
        "event": "chunk_skipped",
        "chunk_id": args.chunk_id,
        "reason": args.reason,
    })
    print(f"Skipped {args.chunk_id}: {args.reason}")
    return 0


def _run_tasks(args: argparse.Namespace) -> int:
    """Execute the tasks subcommand."""
    run_dir = Path(args.run_dir)

    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Error: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        print(f"Error: No manifest.json in {run_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    # Load status if available (for synthesis task availability info)
    status = load_status(run_dir)
    if status is not None:
        status = reconcile_status(status, manifest, run_dir)

    if args.dry_run:
        stale = check_staleness(manifest, run_dir)
        chunks = manifest.get("chunks", [])
        total_files = len(chunks) + 2  # workers + synthesis + index

        if args.json_output:
            json.dump({
                "dry_run": True,
                "total_files": total_files,
                "stale": stale,
                "stale_count": len(stale),
            }, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            if stale:
                print(f"Would write/update {len(stale)} task file(s):")
                for s in stale:
                    print(f"  {s['task_path']} ({s['reason']})")
            else:
                print(f"All {total_files} task files are up to date.")
        return 0

    result = materialize_tasks(manifest, status, run_dir, refresh=args.refresh)

    if args.json_output:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        print(f"Task materialization complete:")
        print(f"  Written: {result['written']}")
        print(f"  Skipped (unchanged): {result['skipped']}")
        print(f"  Total files: {result['total_files']}")
        print(f"  Worker tasks: {result['worker_count']}")

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
        "report": _run_report,
        "synthesize": _run_synthesize,
        "execute": _run_execute,
        "mark": _run_mark,
        "retry": _run_retry,
        "skip": _run_skip,
        "tasks": _run_tasks,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    rc = handler(args)
    if rc != 0:
        sys.exit(rc)
