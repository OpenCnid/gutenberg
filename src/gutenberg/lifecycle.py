"""Worker lifecycle, retry, failure, and resume — Spec 12.

Manages durable worker states, attempt records, result validation,
retry/skip/mark CLI support, and stale-running reconciliation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gutenberg import paths as P
from gutenberg.status import update_chunk_state, save_status, compute_run_state, CHUNK_STATES


# ---------------------------------------------------------------------------
# Required worker output sections (from spec 05)
# ---------------------------------------------------------------------------

REQUIRED_SECTIONS = [
    "# Chunk Summary",
    "# Key Claims / Ideas",
    "# Important Quotes",
    "# Entities / Concepts",
    "# Open Questions",
    "# Connections To Other Chunks",
    "# Synthesis Notes",
]


def get_required_sections() -> list[str]:
    """Return the 7 required section headings from spec 05/12."""
    return list(REQUIRED_SECTIONS)


# ---------------------------------------------------------------------------
# Attempt management
# ---------------------------------------------------------------------------

def create_attempt(
    chunk_id: str,
    executor_type: str,
    model: str | None = None,
    attempt_number: int | None = None,
) -> dict[str, Any]:
    """Create an attempt record with timestamp and metadata."""
    now = datetime.now(timezone.utc).isoformat()
    attempt: dict[str, Any] = {
        "attempt": attempt_number or 1,
        "state": "running",
        "started_at": now,
        "ended_at": None,
        "executor": executor_type,
    }
    if model:
        attempt["model"] = model
    return attempt


def record_attempt_success(
    attempt: dict[str, Any],
    result_path: str,
    log_path: str | None = None,
) -> dict[str, Any]:
    """Fill in success metadata on an attempt record."""
    attempt["state"] = "done"
    attempt["ended_at"] = datetime.now(timezone.utc).isoformat()
    attempt["result_path"] = result_path
    if log_path:
        attempt["log_path"] = log_path
    return attempt


def record_attempt_failure(
    attempt: dict[str, Any],
    error_code: str,
    error_message: str,
    exit_code: int | None = None,
    log_path: str | None = None,
) -> dict[str, Any]:
    """Fill in failure metadata on an attempt record."""
    attempt["state"] = "failed"
    attempt["ended_at"] = datetime.now(timezone.utc).isoformat()
    attempt["error_code"] = error_code
    attempt["error_message"] = error_message
    if exit_code is not None:
        attempt["exit_code"] = exit_code
    if log_path:
        attempt["log_path"] = log_path
    return attempt


# ---------------------------------------------------------------------------
# Result validation
# ---------------------------------------------------------------------------

def validate_worker_result(result_path: Path) -> tuple[bool, str | None]:
    """Validate a worker result file.

    Returns ``(valid, error_reason)``. ``error_reason`` is ``None`` when valid.
    """
    if not result_path.exists():
        return False, "result_file_missing"

    if result_path.stat().st_size == 0:
        return False, "empty_result"

    try:
        content = result_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False, "unreadable_result"

    if not content.strip():
        return False, "whitespace_only"

    return True, None


def check_sections(content: str) -> list[str]:
    """Return list of missing required section headings.

    This is warning-level: missing sections do not fail validation but
    are reported so operators can assess quality.
    """
    missing = []
    for heading in REQUIRED_SECTIONS:
        if heading not in content:
            missing.append(heading)
    return missing


# ---------------------------------------------------------------------------
# Stale-running reconciliation
# ---------------------------------------------------------------------------

def resolve_stale_running(
    status: dict[str, Any],
    manifest: dict[str, Any],
    run_dir: Path,
    timeout_seconds: int = 1800,
) -> list[str]:
    """Find chunks marked ``running`` longer than *timeout_seconds*.

    Promotes to ``done`` if a valid result exists, otherwise marks ``failed``
    with reason ``interrupted_or_stale``.

    Returns list of chunk IDs that were resolved.
    """
    resolved: list[str] = []
    now = datetime.now(timezone.utc)

    for c in manifest.get("chunks", []):
        cid = c["id"]
        entry = status["chunks"].get(cid)
        if entry is None or entry["state"] != "running":
            continue

        # Find the timestamp of the running transition
        running_since = None
        for t in reversed(entry.get("transitions", [])):
            if t["state"] == "running":
                running_since = t["timestamp"]
                break

        if running_since is None:
            continue

        # Parse timestamp — handle both offset-aware and naive
        started = datetime.fromisoformat(running_since)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)

        elapsed = (now - started).total_seconds()
        if elapsed < timeout_seconds:
            continue

        # Check if a valid result exists
        result_file = P.worker_result_path(run_dir, cid)
        valid, _ = validate_worker_result(result_file)

        if valid:
            update_chunk_state(status, cid, "done")
        else:
            update_chunk_state(status, cid, "failed")
            entry["last_error"] = {
                "code": "interrupted_or_stale",
                "message": f"Chunk was running for {int(elapsed)}s (timeout: {timeout_seconds}s) with no valid result.",
            }

        resolved.append(cid)

    return resolved


# ---------------------------------------------------------------------------
# Mark / retry / skip operations
# ---------------------------------------------------------------------------

def mark_chunk(
    status: dict[str, Any],
    chunk_id: str,
    state: str,
    reason: str | None = None,
    run_dir: Path | None = None,
) -> None:
    """Apply ``gutenberg mark`` logic with validation.

    Raises ``ValueError`` for invalid transitions.
    """
    if chunk_id not in status["chunks"]:
        raise ValueError(f"Unknown chunk: {chunk_id}")

    if state not in CHUNK_STATES:
        raise ValueError(f"Invalid state: {state!r}")

    if state in ("failed", "skipped") and not reason:
        raise ValueError(f"--reason is required when marking as {state}")

    if state == "done" and run_dir is not None:
        result_file = P.worker_result_path(run_dir, chunk_id)
        valid, err = validate_worker_result(result_file)
        if not valid:
            raise ValueError(
                f"Cannot mark {chunk_id} as done: result validation failed ({err}). "
                f"Expected valid file at {result_file}."
            )

    update_chunk_state(status, chunk_id, state)

    entry = status["chunks"][chunk_id]
    if reason:
        entry["reason"] = reason
    if state == "failed" and reason:
        entry["last_error"] = {
            "code": "manual_mark",
            "message": reason,
        }


def retry_chunks(
    status: dict[str, Any],
    manifest: dict[str, Any],
    which: str = "failed",
    chunk_ids: list[str] | None = None,
    force: bool = False,
) -> list[str]:
    """Reset eligible chunks to ``pending``.

    *which*: ``"failed"`` resets failed/missing chunks.
    *chunk_ids*: if given, only reset those specific chunks.
    *force*: if True, ignore max_attempts limit.

    Returns list of chunk IDs that were reset.
    """
    max_attempts = get_max_attempts(manifest)
    eligible_states = {"failed", "missing", "skipped"}
    reset: list[str] = []

    targets = chunk_ids if chunk_ids else list(status["chunks"].keys())

    for cid in targets:
        if cid not in status["chunks"]:
            continue
        entry = status["chunks"][cid]
        if entry["state"] not in eligible_states:
            continue

        attempt_count = len(entry.get("attempts", []))
        if not force and attempt_count >= max_attempts:
            continue

        update_chunk_state(status, cid, "pending")
        # Clear last_error on retry but preserve attempts history
        entry.pop("last_error", None)
        entry.pop("reason", None)
        reset.append(cid)

    return reset


def skip_chunk(
    status: dict[str, Any],
    chunk_id: str,
    reason: str,
) -> None:
    """Mark a chunk as ``skipped`` with a reason."""
    if chunk_id not in status["chunks"]:
        raise ValueError(f"Unknown chunk: {chunk_id}")
    if not reason:
        raise ValueError("--reason is required for skip")

    update_chunk_state(status, chunk_id, "skipped")
    entry = status["chunks"][chunk_id]
    entry["reason"] = reason


def get_max_attempts(manifest: dict[str, Any]) -> int:
    """Read max attempts from manifest executor config or use default 3."""
    executor = manifest.get("executor", {})
    return executor.get("max_attempts", 3)
