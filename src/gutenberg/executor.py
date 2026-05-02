"""Executor / Worker Launch Integration — Spec 11.

Provides the execution layer that launches worker tasks, records lifecycle
data, validates results, and respects concurrency bounds.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from gutenberg import paths as P
from gutenberg.lifecycle import (
    create_attempt,
    record_attempt_success,
    record_attempt_failure,
    validate_worker_result,
    resolve_stale_running,
)
from gutenberg.reporting import append_event, write_orchestration_summary
from gutenberg.status import (
    load_status,
    save_status,
    update_chunk_state,
    reconcile_status,
    infer_status,
)
from gutenberg.tasks import materialize_tasks


# ---------------------------------------------------------------------------
# Executor result and protocol
# ---------------------------------------------------------------------------

@dataclass
class ExecutorResult:
    success: bool
    exit_code: int | None = None
    error_message: str | None = None
    log_path: str | None = None


class ExecutorProtocol(Protocol):
    def launch(self, task_path: str, result_path: str, timeout: int) -> ExecutorResult: ...


# ---------------------------------------------------------------------------
# Executor implementations
# ---------------------------------------------------------------------------

class CommandExecutor:
    """Runs a configured command template via subprocess."""

    def __init__(
        self,
        command: list[str],
        output_mode: str = "file",
        cwd: str | None = None,
    ):
        self.command_template = command
        self.output_mode = output_mode  # "file" or "stdout"
        self.cwd = cwd

    def launch(self, task_path: str, result_path: str, timeout: int) -> ExecutorResult:
        # Substitute template variables
        run_dir = str(Path(task_path).parent.parent.parent)  # tasks/workers/X.md -> run_dir
        chunk_id = Path(task_path).stem.replace(".worker", "")

        subs = {
            "{task_path}": task_path,
            "{result_path}": result_path,
            "{run_dir}": run_dir,
            "{chunk_id}": chunk_id,
            "{chunk_path}": str(Path(run_dir) / P.CHUNKS_DIR / f"{chunk_id}.md"),
            "{worker_prompt_path}": str(Path(run_dir) / P.PROMPTS_DIR / P.WORKER_PROMPT),
        }

        cmd = []
        for part in self.command_template:
            for k, v in subs.items():
                part = part.replace(k, v)
            cmd.append(part)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.cwd,
            )
        except FileNotFoundError:
            return ExecutorResult(
                success=False,
                error_message=f"Command not found: {cmd[0]}",
            )
        except subprocess.TimeoutExpired:
            return ExecutorResult(
                success=False,
                error_message=f"Worker timed out after {timeout}s",
            )

        if self.output_mode == "stdout" and proc.returncode == 0:
            # Write stdout to result path
            Path(result_path).write_text(proc.stdout, encoding="utf-8")

        if proc.returncode != 0:
            return ExecutorResult(
                success=False,
                exit_code=proc.returncode,
                error_message=f"Executor exited with code {proc.returncode}",
            )

        return ExecutorResult(success=True, exit_code=0)


class ManualExecutor:
    """No-op executor that prints instructions. Preserves V2 behavior."""

    def launch(self, task_path: str, result_path: str, timeout: int) -> ExecutorResult:
        print(f"Manual executor — task: {task_path}, result: {result_path}")
        return ExecutorResult(
            success=False,
            error_message="manual executor — no automatic execution",
        )


# ---------------------------------------------------------------------------
# Executor config
# ---------------------------------------------------------------------------

_VALID_TEMPLATE_VARS = {
    "{run_dir}", "{chunk_id}", "{chunk_path}",
    "{task_path}", "{result_path}", "{worker_prompt_path}",
}


def load_executor_config(
    config_path: str | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and merge executor config from file and CLI overrides."""
    config: dict[str, Any] = {}

    if config_path:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f).get("executor", {})

    if cli_overrides:
        config.update(cli_overrides)

    return config


def validate_executor_config(config: dict[str, Any]) -> list[str]:
    """Validate executor config. Returns list of errors."""
    errors: list[str] = []

    exec_type = config.get("type", "command")
    if exec_type not in ("command", "clawd", "manual"):
        errors.append(f"Unknown executor type: {exec_type}")

    command = config.get("command", [])
    if exec_type in ("command", "clawd") and not command:
        errors.append("Executor type requires 'command' field")

    # Check for unknown template variables
    if command:
        for part in command:
            # Find all {xxx} patterns
            import re
            for match in re.finditer(r"\{[^}]+\}", part):
                var = match.group()
                if var not in _VALID_TEMPLATE_VARS:
                    errors.append(f"Unknown template variable: {var}")

    concurrency = config.get("concurrency", 1)
    if not isinstance(concurrency, int) or concurrency < 1:
        errors.append(f"Concurrency must be a positive integer, got: {concurrency}")

    timeout = config.get("timeout_seconds", 1800)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        errors.append(f"Timeout must be positive, got: {timeout}")

    return errors


def create_executor(config: dict[str, Any]) -> ExecutorProtocol:
    """Factory: create an executor from config."""
    exec_type = config.get("type", "command")

    if exec_type == "manual":
        return ManualExecutor()

    command = config.get("command", [])
    output_mode = config.get("output_mode", "file")
    cwd = config.get("cwd")

    return CommandExecutor(command=command, output_mode=output_mode, cwd=cwd)


# ---------------------------------------------------------------------------
# Main execution loop
# ---------------------------------------------------------------------------

def execute_workers(
    manifest: dict[str, Any],
    status: dict[str, Any],
    run_dir: Path,
    executor: ExecutorProtocol,
    concurrency: int = 1,
    only: list[str] | None = None,
    retry_failed: bool = False,
    timeout: int = 1800,
    executor_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Launch workers for eligible chunks.

    Returns an execution summary dict.
    """
    # Reconcile status and resolve stale running
    status = reconcile_status(status, manifest, run_dir)
    resolve_stale_running(status, manifest, run_dir, timeout_seconds=timeout)

    # Materialize tasks if missing
    tasks_index = P.tasks_index_path(run_dir)
    if not tasks_index.exists():
        materialize_tasks(manifest, status, run_dir)

    # Build eligible queue
    chunks = manifest.get("chunks", [])
    eligible: list[dict[str, Any]] = []

    for chunk in chunks:
        cid = chunk["id"]
        if only and cid not in only:
            continue

        entry = status["chunks"].get(cid)
        if entry is None:
            continue

        state = entry["state"]
        if state in ("pending", "missing"):
            eligible.append(chunk)
        elif state == "failed" and retry_failed:
            eligible.append(chunk)
        # done, skipped, running — skip

    # Shutdown flag
    shutdown_requested = False
    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def _shutdown_handler(signum, frame):
        nonlocal shutdown_requested
        shutdown_requested = True

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    summary: dict[str, Any] = {
        "launched": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped_existing": 0,
        "interrupted": False,
        "chunks": {},
    }

    def _write_attempt_log(
        cid: str, attempt_num: int, result: ExecutorResult,
    ) -> str | None:
        """Write a bounded per-attempt log file. Returns relative log path."""
        log_path = P.worker_log_path(run_dir, cid, attempt_num)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        lines.append(f"Worker attempt {attempt_num} for {cid}")
        lines.append(f"Exit code: {result.exit_code}")
        lines.append(f"Success: {result.success}")
        if result.error_message:
            lines.append(f"Error: {result.error_message}")
        log_content = "\n".join(lines)
        # Bound to 512KB per spec 15
        if len(log_content.encode("utf-8")) > 524288:
            log_content = log_content[:524288] + "\n[TRUNCATED]"
        log_path.write_text(log_content, encoding="utf-8")
        return str(log_path.relative_to(run_dir))

    def _process_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
        """Process a single chunk. Returns per-chunk result."""
        cid = chunk["id"]
        task_path = P.worker_task_path(run_dir, cid)
        result_path = P.worker_result_path(run_dir, cid)

        entry = status["chunks"][cid]
        attempt_num = len(entry.get("attempts", [])) + 1
        attempt = create_attempt(cid, type(executor).__name__, attempt_number=attempt_num)

        # Ensure attempts list exists
        if "attempts" not in entry:
            entry["attempts"] = []

        # Mark running and emit event
        update_chunk_state(status, cid, "running")
        entry["attempts"].append(attempt)
        save_status(status, run_dir)
        append_event(run_dir, {
            "event": "worker_started",
            "chunk_id": cid,
            "attempt": attempt_num,
        })

        # Launch
        result = executor.launch(
            task_path=str(task_path),
            result_path=str(result_path),
            timeout=timeout,
        )

        # Write per-attempt log
        log_rel = _write_attempt_log(cid, attempt_num, result)

        # Validate result
        if result.success:
            valid, err = validate_worker_result(result_path)
            if valid:
                record_attempt_success(
                    attempt,
                    result_path=str(result_path.relative_to(run_dir)),
                    log_path=log_rel,
                )
                update_chunk_state(status, cid, "done")
                entry["result_path"] = str(result_path.relative_to(run_dir))
                append_event(run_dir, {
                    "event": "worker_done",
                    "chunk_id": cid,
                    "attempt": attempt_num,
                })
                return {"chunk_id": cid, "state": "done"}
            else:
                record_attempt_failure(
                    attempt,
                    error_code=err or "invalid_result",
                    error_message=f"Result validation failed: {err}",
                    exit_code=result.exit_code,
                    log_path=log_rel,
                )
                update_chunk_state(status, cid, "failed")
                entry["last_error"] = {
                    "code": err or "invalid_result",
                    "message": f"Result validation failed: {err}",
                }
                append_event(run_dir, {
                    "event": "worker_failed",
                    "chunk_id": cid,
                    "attempt": attempt_num,
                    "error": err or "invalid_result",
                })
                return {"chunk_id": cid, "state": "failed", "error": err}
        else:
            error_code = "executor_exit_nonzero" if result.exit_code else "executor_error"
            record_attempt_failure(
                attempt,
                error_code=error_code,
                error_message=result.error_message or "Unknown error",
                exit_code=result.exit_code,
                log_path=log_rel,
            )
            update_chunk_state(status, cid, "failed")
            entry["last_error"] = {
                "code": error_code,
                "message": result.error_message or "Unknown error",
            }
            append_event(run_dir, {
                "event": "worker_failed",
                "chunk_id": cid,
                "attempt": attempt_num,
                "error": error_code,
            })
            return {"chunk_id": cid, "state": "failed", "error": result.error_message}

    try:
        if concurrency <= 1:
            # Sequential execution
            for chunk in eligible:
                if shutdown_requested:
                    summary["interrupted"] = True
                    break
                summary["launched"] += 1
                chunk_result = _process_chunk(chunk)
                summary["chunks"][chunk["id"]] = chunk_result
                if chunk_result["state"] == "done":
                    summary["succeeded"] += 1
                else:
                    summary["failed"] += 1
                save_status(status, run_dir)
        else:
            # Concurrent execution
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {}
                for chunk in eligible:
                    if shutdown_requested:
                        summary["interrupted"] = True
                        break
                    future = pool.submit(_process_chunk, chunk)
                    futures[future] = chunk
                    summary["launched"] += 1

                for future in as_completed(futures):
                    if shutdown_requested:
                        summary["interrupted"] = True
                    chunk_result = future.result()
                    summary["chunks"][chunk_result["chunk_id"]] = chunk_result
                    if chunk_result["state"] == "done":
                        summary["succeeded"] += 1
                    else:
                        summary["failed"] += 1
                    save_status(status, run_dir)

    finally:
        # Restore signal handlers
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)
        # Final status save
        save_status(status, run_dir)
        # Write orchestration summary
        write_orchestration_summary(manifest, status, run_dir, executor_config)

    return summary
