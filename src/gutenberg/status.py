"""Run status tracking — per-chunk completion state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gutenberg import paths as P

CHUNK_STATES = ("pending", "running", "done", "failed", "missing")
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
    """Write ``status.json`` to *run_dir*."""
    p = P.status_path(run_dir)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
        f.write("\n")
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
    if "done" in states and states <= {"done", "failed", "missing"}:
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
