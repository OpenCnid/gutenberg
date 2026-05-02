"""Synthesis execution — Spec 13.

Runs the synthesis step through the same executor discipline as workers:
readiness checks, partial synthesis, status recording, output validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gutenberg import paths as P
from gutenberg.executor import ExecutorProtocol, ExecutorResult
from gutenberg.lifecycle import (
    create_attempt,
    record_attempt_success,
    record_attempt_failure,
    validate_worker_result,
)
from gutenberg.reporting import append_event, get_log_limits, enforce_run_log_cap
from gutenberg.status import save_status
from gutenberg.tasks import generate_synthesis_task


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------

def check_synthesis_readiness(
    manifest: dict[str, Any],
    status: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    """Check whether synthesis can proceed.

    Returns a dict with ``ready``, ``blockers``, ``state``, input counts, etc.
    """
    chunks = manifest.get("chunks", [])
    chunk_statuses = status.get("chunks", {})

    total = len(chunks)
    available = 0
    missing: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    pending: list[str] = []
    running: list[str] = []

    for chunk in chunks:
        cid = chunk["id"]
        cs = chunk_statuses.get(cid, {})
        state = cs.get("state", "pending")

        if state == "done":
            result_file = P.worker_result_path(run_dir, cid)
            if result_file.exists() and result_file.stat().st_size > 0:
                available += 1
            else:
                missing.append(cid)
        elif state == "failed":
            failed.append(cid)
        elif state == "skipped":
            skipped.append(cid)
        elif state == "running":
            running.append(cid)
        elif state == "missing":
            missing.append(cid)
        else:
            pending.append(cid)

    blockers: list[str] = []
    if pending:
        blockers.append(f"{len(pending)} chunk(s) still pending")
    if running:
        blockers.append(f"{len(running)} chunk(s) still running")
    if failed:
        blockers.append(f"{len(failed)} chunk(s) failed")
    if missing:
        blockers.append(f"{len(missing)} chunk(s) missing results")
    if skipped:
        blockers.append(f"{len(skipped)} chunk(s) skipped")

    ready = len(blockers) == 0

    # Determine current synthesis state
    synth_status = status.get("synthesis", {})
    synth_state = synth_status.get("state", "not_started")
    if ready and synth_state == "not_started":
        synth_state = "ready"
    elif not ready and synth_state == "not_started":
        synth_state = "blocked"

    return {
        "ready": ready,
        "blockers": blockers,
        "state": synth_state,
        "input_chunks": total,
        "available_results": available,
        "missing_chunks": missing,
        "failed_chunks": failed,
        "skipped_chunks": skipped,
        "pending_chunks": pending,
    }


# ---------------------------------------------------------------------------
# Synthesis inputs
# ---------------------------------------------------------------------------

def build_synthesis_inputs(
    manifest: dict[str, Any],
    status: dict[str, Any],
    run_dir: Path,
) -> list[dict[str, Any]]:
    """Build ordered list of worker result entries with availability info."""
    chunks = manifest.get("chunks", [])
    chunk_statuses = status.get("chunks", {})
    inputs: list[dict[str, Any]] = []

    for chunk in chunks:
        cid = chunk["id"]
        result_path = P.worker_result_path(run_dir, cid)
        cs = chunk_statuses.get(cid, {})
        state = cs.get("state", "pending")
        exists = result_path.exists() and result_path.stat().st_size > 0

        inputs.append({
            "chunk_id": cid,
            "chunk_number": chunk["chunk_number"],
            "result_path": str(result_path.relative_to(run_dir)),
            "state": state,
            "available": state == "done" and exists,
        })

    return inputs


# ---------------------------------------------------------------------------
# Synthesis execution
# ---------------------------------------------------------------------------

def execute_synthesis(
    manifest: dict[str, Any],
    status: dict[str, Any],
    run_dir: Path,
    executor: ExecutorProtocol,
    partial: bool = False,
    force: bool = False,
    timeout: int = 1800,
) -> dict[str, Any]:
    """Run synthesis.

    Returns a result summary dict.
    """
    readiness = check_synthesis_readiness(manifest, status, run_dir)

    # Refuse if not ready and not partial
    if not readiness["ready"] and not partial:
        return {
            "success": False,
            "state": "blocked",
            "reason": "Synthesis not ready",
            "blockers": readiness["blockers"],
        }

    # Check existing synthesis output
    synth_result_path = P.synthesis_result_path(run_dir)
    if synth_result_path.exists() and synth_result_path.stat().st_size > 0 and not force:
        return {
            "success": False,
            "state": "blocked",
            "reason": f"Synthesis output already exists: {synth_result_path.relative_to(run_dir)}. Use --force to overwrite.",
        }

    # Regenerate synthesis task with current availability
    synth_task_content = generate_synthesis_task(
        manifest, status, run_dir.name, partial=partial,
    )
    synth_task_path = P.synthesis_task_path(run_dir)
    synth_task_path.parent.mkdir(parents=True, exist_ok=True)
    synth_task_path.write_text(synth_task_content, encoding="utf-8")

    # Initialize synthesis status if not present
    if "synthesis" not in status:
        status["synthesis"] = {
            "state": "not_started",
            "result_path": str(synth_result_path.relative_to(run_dir)),
            "task_path": str(synth_task_path.relative_to(run_dir)),
            "partial": False,
            "input_chunks": readiness["input_chunks"],
            "available_results": readiness["available_results"],
            "missing_chunks": readiness["missing_chunks"],
            "attempts": [],
        }

    synth_entry = status["synthesis"]
    attempt_num = len(synth_entry.get("attempts", [])) + 1
    attempt = create_attempt("synthesis", type(executor).__name__, attempt_number=attempt_num)

    if "attempts" not in synth_entry:
        synth_entry["attempts"] = []

    # Mark running
    synth_entry["state"] = "running"
    synth_entry["attempts"].append(attempt)
    save_status(status, run_dir)

    append_event(run_dir, {
        "event": "synthesis_started",
        "attempt": attempt_num,
        "partial": partial,
    })

    # Launch executor
    result = executor.launch(
        task_path=str(synth_task_path),
        result_path=str(synth_result_path),
        timeout=timeout,
    )

    # Write per-attempt synthesis log
    per_attempt_max, per_run_max = get_log_limits(manifest)
    synth_log_path = P.synthesis_log_path(run_dir, attempt_num)
    synth_log_path.parent.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = [
        f"Synthesis attempt {attempt_num}",
        f"Exit code: {result.exit_code}",
        f"Success: {result.success}",
    ]
    if result.error_message:
        log_lines.append(f"Error: {result.error_message}")
    log_content = "\n".join(log_lines)
    if len(log_content.encode("utf-8")) > per_attempt_max:
        log_content = log_content[:per_attempt_max] + "\n[TRUNCATED]"
    synth_log_path.write_text(log_content, encoding="utf-8")
    enforce_run_log_cap(run_dir, per_run_max)
    log_rel = str(synth_log_path.relative_to(run_dir))

    # Validate output
    if result.success:
        valid, err = validate_worker_result(synth_result_path)
        if valid:
            record_attempt_success(
                attempt,
                result_path=str(synth_result_path.relative_to(run_dir)),
                log_path=log_rel,
            )
            if partial:
                synth_entry["state"] = "partial"
                synth_entry["partial"] = True
            else:
                synth_entry["state"] = "done"
                synth_entry["partial"] = False

            synth_entry["available_results"] = readiness["available_results"]
            synth_entry["missing_chunks"] = readiness["missing_chunks"]
            save_status(status, run_dir)

            append_event(run_dir, {
                "event": "synthesis_done",
                "attempt": attempt_num,
                "state": synth_entry["state"],
            })

            return {
                "success": True,
                "state": synth_entry["state"],
                "result_path": str(synth_result_path.relative_to(run_dir)),
                "partial": partial,
                "available_results": readiness["available_results"],
                "input_chunks": readiness["input_chunks"],
            }
        else:
            record_attempt_failure(
                attempt,
                error_code=err or "invalid_result",
                error_message=f"Synthesis validation failed: {err}",
                exit_code=result.exit_code,
                log_path=log_rel,
            )
            synth_entry["state"] = "failed"
            synth_entry["last_error"] = {
                "code": err or "invalid_result",
                "message": f"Synthesis validation failed: {err}",
            }
            save_status(status, run_dir)

            append_event(run_dir, {
                "event": "synthesis_failed",
                "attempt": attempt_num,
                "error": err or "invalid_result",
            })

            return {
                "success": False,
                "state": "failed",
                "reason": f"Synthesis validation failed: {err}",
            }
    else:
        error_code = "executor_exit_nonzero" if result.exit_code else "executor_error"
        record_attempt_failure(
            attempt,
            error_code=error_code,
            error_message=result.error_message or "Unknown error",
            exit_code=result.exit_code,
            log_path=log_rel,
        )
        synth_entry["state"] = "failed"
        synth_entry["last_error"] = {
            "code": error_code,
            "message": result.error_message or "Unknown error",
        }
        save_status(status, run_dir)

        append_event(run_dir, {
            "event": "synthesis_failed",
            "attempt": attempt_num,
            "error": error_code,
        })

        return {
            "success": False,
            "state": "failed",
            "reason": result.error_message,
        }
