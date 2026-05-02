"""Run status tracking — per-chunk completion state."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gutenberg import paths as P

CHUNK_STATES = ("pending", "running", "done", "failed", "missing", "skipped")
RUN_STATES = ("ingested", "in_progress", "complete", "partial")


def create_status(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build initial status from manifest. All chunks start as ``pending``."""
    now = datetime.now(timezone.utc).isoformat()
    chunks: dict[str, Any] = {}
    for c in manifest.get("chunks", []):
        cid = c["id"]
        chunks[cid] = {
            "state": "pending",
            "transitions": [{"state": "pending", "timestamp": now}],
        }
    return {
        "run_state": "ingested",
        "chunks": chunks,
        "summary": _summarize(chunks),
    }


def load_status(run_dir: Path) -> dict[str, Any] | None:
    """Read ``status.json`` from *run_dir*. Returns ``None`` if absent."""
    p = P.status_path(run_dir)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_status(status: dict[str, Any], run_dir: Path) -> Path:
    """Write ``status.json`` to *run_dir* atomically."""
    p = P.status_path(run_dir)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)
    return p


def update_chunk_state(status: dict[str, Any], chunk_id: str, new_state: str) -> None:
    """Transition *chunk_id* to *new_state*, recording a timestamp."""
    if new_state not in CHUNK_STATES:
        raise ValueError(f"Invalid chunk state: {new_state!r}")
    entry = status["chunks"][chunk_id]
    entry["state"] = new_state
    entry["transitions"].append({
        "state": new_state,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    status["run_state"] = compute_run_state(status)
    status["summary"] = _summarize(status["chunks"])


def compute_run_state(status: dict[str, Any]) -> str:
    """Derive the run-level state from per-chunk states."""
    states = {e["state"] for e in status["chunks"].values()}
    if not states:
        return "ingested"
    if states == {"pending"}:
        return "ingested"
    if states == {"done"}:
        return "complete"
    if "done" in states and states <= {"done", "failed", "missing", "skipped"}:
        return "partial"
    return "in_progress"


def infer_status(manifest: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Build a status dict for V1 runs that lack ``status.json``.

    Scans the filesystem: result file exists and non-empty → ``done``, else ``pending``.
    """
    now = datetime.now(timezone.utc).isoformat()
    chunks: dict[str, Any] = {}
    for c in manifest.get("chunks", []):
        cid = c["id"]
        result_file = P.worker_result_path(run_dir, cid)
        if result_file.exists() and result_file.stat().st_size > 0:
            state = "done"
        else:
            state = "pending"
        chunks[cid] = {
            "state": state,
            "transitions": [{"state": state, "timestamp": now}],
        }
    status = {
        "run_state": "",
        "chunks": chunks,
        "summary": _summarize(chunks),
    }
    status["run_state"] = compute_run_state(status)
    return status


def _validate_result_content(result_file: Path) -> tuple[bool, str | None]:
    """Check if a result file has valid readable content.

    Returns ``(valid, error_reason)``.
    """
    if not result_file.exists():
        return False, "result_file_missing"
    if result_file.stat().st_size == 0:
        return False, "empty_result"
    try:
        content = result_file.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False, "unreadable_result"
    if not content.strip():
        return False, "whitespace_only"
    return True, None


def reconcile_status(
    status: dict[str, Any],
    manifest: dict[str, Any],
    run_dir: Path,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Reconcile status.json with filesystem reality.

    Handles V3 states: promotes valid results to done, demotes missing/invalid
    results, resolves stale running chunks, and reports unknown chunks.
    """
    changed = False
    now = datetime.now(timezone.utc).isoformat()
    manifest_ids = {c["id"] for c in manifest.get("chunks", [])}

    # Report unknown chunks in status (not in manifest) without crashing
    unknown_ids = set(status.get("chunks", {}).keys()) - manifest_ids
    if unknown_ids:
        if "_warnings" not in status:
            status["_warnings"] = []
        for uid in sorted(unknown_ids):
            warning = f"Chunk {uid} in status.json but not in manifest"
            if warning not in status["_warnings"]:
                status["_warnings"].append(warning)

    for c in manifest.get("chunks", []):
        cid = c["id"]
        if cid not in status["chunks"]:
            # Manifest chunk missing from status — add as pending or done
            result_file = P.worker_result_path(run_dir, cid)
            valid, _ = _validate_result_content(result_file)
            state = "done" if valid else "pending"
            status["chunks"][cid] = {
                "state": state,
                "transitions": [{"state": state, "timestamp": now}],
            }
            changed = True
            continue

        entry = status["chunks"][cid]
        result_file = P.worker_result_path(run_dir, cid)
        valid, err = _validate_result_content(result_file)

        # Resolve stale running: chunk marked running too long
        if entry["state"] == "running":
            running_since = None
            for t in reversed(entry.get("transitions", [])):
                if t["state"] == "running":
                    running_since = t["timestamp"]
                    break
            if running_since is not None:
                started = datetime.fromisoformat(running_since)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if elapsed >= timeout_seconds:
                    if valid:
                        update_chunk_state(status, cid, "done")
                    else:
                        update_chunk_state(status, cid, "failed")
                        entry["last_error"] = {
                            "code": "interrupted_or_stale",
                            "message": f"Chunk was running for {int(elapsed)}s (timeout: {timeout_seconds}s) with no valid result.",
                        }
                    changed = True
                    continue

        if valid and entry["state"] in ("pending", "missing", "running"):
            update_chunk_state(status, cid, "done")
            changed = True
        elif entry["state"] == "done" and not valid:
            if err == "result_file_missing":
                update_chunk_state(status, cid, "missing")
            else:
                # Empty, unreadable, or whitespace-only → failed with reason
                update_chunk_state(status, cid, "failed")
                entry["last_error"] = {
                    "code": err or "invalid_result",
                    "message": f"Result file validation failed: {err}",
                }
            changed = True
        # skipped state is preserved — don't promote even if result exists

    if changed:
        status["run_state"] = compute_run_state(status)
        status["summary"] = _summarize(status["chunks"])
        save_status(status, run_dir)

    return status


def summarize_status(status: dict[str, Any]) -> dict[str, Any]:
    """Return a summary dict: total + per-state counts + run_state."""
    result = _summarize(status["chunks"])
    result["run_state"] = status.get("run_state", compute_run_state(status))
    return result


def _summarize(chunks: dict[str, Any]) -> dict[str, int]:
    """Count per-state totals."""
    counts: dict[str, int] = {s: 0 for s in CHUNK_STATES}
    for entry in chunks.values():
        s = entry["state"]
        counts[s] = counts.get(s, 0) + 1
    counts["total"] = len(chunks)
    return counts


def summarize_failures(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Return details for failed/skipped/missing chunks."""
    problems: list[dict[str, Any]] = []
    for cid, entry in status.get("chunks", {}).items():
        if entry["state"] in ("failed", "skipped", "missing"):
            info: dict[str, Any] = {
                "chunk_id": cid,
                "state": entry["state"],
            }
            if "last_error" in entry:
                info["last_error"] = entry["last_error"]
            if "reason" in entry:
                info["reason"] = entry["reason"]
            attempts = entry.get("attempts", [])
            if attempts:
                info["attempt_count"] = len(attempts)
            problems.append(info)
    return problems
