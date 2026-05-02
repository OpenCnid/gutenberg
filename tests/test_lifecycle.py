"""Tests for worker lifecycle, retry, failure, and resume (Spec 12)."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gutenberg.lifecycle import (
    create_attempt,
    record_attempt_success,
    record_attempt_failure,
    validate_worker_result,
    check_sections,
    get_required_sections,
    resolve_stale_running,
    mark_chunk,
    retry_chunks,
    skip_chunk,
    get_max_attempts,
)
from gutenberg.status import (
    create_status,
    load_status,
    save_status,
    update_chunk_state,
    compute_run_state,
    reconcile_status,
    summarize_status,
    summarize_failures,
    CHUNK_STATES,
)
from gutenberg.cli import main
from gutenberg import paths as P


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_manifest(num_chunks: int = 3) -> dict:
    chunks = []
    for i in range(num_chunks):
        cid = f"chunk-{i + 1:04d}"
        chunks.append({
            "id": cid,
            "path": f"chunks/{cid}.md",
            "char_start": i * 50000,
            "char_end": (i + 1) * 50000,
            "estimated_tokens": 12500,
            "heading_context": [],
            "chunk_index": i,
            "chunk_number": i + 1,
            "total_chunks": num_chunks,
            "prev_context": "",
            "next_context": "",
        })
    return {
        "schema_version": "1.0",
        "source": {"title": "Test", "author": "Author"},
        "settings": {"chunk_size": 50000, "overlap": 2000},
        "chunks": chunks,
        "results": {"directory": "results"},
        "prompts": {
            "orchestrator": "prompts/orchestrator.md",
            "worker": "prompts/worker.md",
            "synthesis": "prompts/synthesis.md",
        },
    }


def _setup_run(tmp_path: Path, manifest: dict, status: dict | None = None) -> Path:
    run_dir = tmp_path / "test-run"
    run_dir.mkdir(parents=True)
    P.chunks_dir(run_dir).mkdir()
    P.prompts_dir(run_dir).mkdir()
    P.results_dir(run_dir).mkdir()

    with open(P.manifest_path(run_dir), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    for c in manifest["chunks"]:
        (run_dir / c["path"]).write_text(f"# {c['id']}\n", encoding="utf-8")

    P.orchestrator_prompt_path(run_dir).write_text("orch\n")
    P.worker_prompt_path(run_dir).write_text("worker\n")
    P.synthesis_prompt_path(run_dir).write_text("synth\n")
    P.source_path(run_dir).write_text("source\n")

    if status is None:
        status = create_status(manifest)
    save_status(status, run_dir)
    return run_dir


def _write_result(run_dir: Path, chunk_id: str, content: str = "# Chunk Summary\nGood.\n") -> Path:
    p = P.worker_result_path(run_dir, chunk_id)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Skipped state in run state computation
# ---------------------------------------------------------------------------

class TestSkippedState:
    def test_skipped_in_chunk_states(self):
        assert "skipped" in CHUNK_STATES

    def test_run_state_done_and_skipped_is_partial(self):
        manifest = _make_manifest(2)
        status = create_status(manifest)
        update_chunk_state(status, "chunk-0001", "done")
        update_chunk_state(status, "chunk-0002", "skipped")
        assert compute_run_state(status) == "partial"

    def test_run_state_done_failed_skipped_is_partial(self):
        manifest = _make_manifest(3)
        status = create_status(manifest)
        update_chunk_state(status, "chunk-0001", "done")
        update_chunk_state(status, "chunk-0002", "failed")
        update_chunk_state(status, "chunk-0003", "skipped")
        assert compute_run_state(status) == "partial"

    def test_run_state_all_done_is_complete(self):
        manifest = _make_manifest(2)
        status = create_status(manifest)
        update_chunk_state(status, "chunk-0001", "done")
        update_chunk_state(status, "chunk-0002", "done")
        assert compute_run_state(status) == "complete"


# ---------------------------------------------------------------------------
# Attempt management
# ---------------------------------------------------------------------------

class TestAttempts:
    def test_create_attempt_fields(self):
        a = create_attempt("chunk-0001", "command", model="gpt-5.5")
        assert a["attempt"] == 1
        assert a["state"] == "running"
        assert a["started_at"] is not None
        assert a["ended_at"] is None
        assert a["executor"] == "command"
        assert a["model"] == "gpt-5.5"

    def test_create_attempt_no_model(self):
        a = create_attempt("chunk-0001", "manual")
        assert "model" not in a

    def test_record_success(self):
        a = create_attempt("chunk-0001", "command")
        record_attempt_success(a, "results/chunk-0001.analysis.md", "logs/chunk-0001.log")
        assert a["state"] == "done"
        assert a["ended_at"] is not None
        assert a["result_path"] == "results/chunk-0001.analysis.md"
        assert a["log_path"] == "logs/chunk-0001.log"

    def test_record_failure(self):
        a = create_attempt("chunk-0001", "command")
        record_attempt_failure(a, "executor_exit_nonzero", "exit code 1", exit_code=1)
        assert a["state"] == "failed"
        assert a["error_code"] == "executor_exit_nonzero"
        assert a["error_message"] == "exit code 1"
        assert a["exit_code"] == 1


# ---------------------------------------------------------------------------
# Result validation
# ---------------------------------------------------------------------------

class TestResultValidation:
    def test_valid_result(self, tmp_path):
        p = tmp_path / "result.md"
        p.write_text("# Chunk Summary\nContent here.\n")
        valid, err = validate_worker_result(p)
        assert valid
        assert err is None

    def test_missing_result(self, tmp_path):
        p = tmp_path / "nonexistent.md"
        valid, err = validate_worker_result(p)
        assert not valid
        assert err == "result_file_missing"

    def test_empty_result(self, tmp_path):
        p = tmp_path / "result.md"
        p.write_text("")
        valid, err = validate_worker_result(p)
        assert not valid
        assert err == "empty_result"

    def test_whitespace_only_result(self, tmp_path):
        p = tmp_path / "result.md"
        p.write_text("   \n\n  \t  \n")
        valid, err = validate_worker_result(p)
        assert not valid
        assert err == "whitespace_only"

    def test_unreadable_result(self, tmp_path):
        p = tmp_path / "result.md"
        p.write_bytes(b"\x80\x81\x82\x83")  # invalid UTF-8
        valid, err = validate_worker_result(p)
        assert not valid
        assert err == "unreadable_result"


# ---------------------------------------------------------------------------
# Section checking
# ---------------------------------------------------------------------------

class TestSectionCheck:
    def test_all_sections_present(self):
        content = "\n".join(get_required_sections())
        missing = check_sections(content)
        assert missing == []

    def test_missing_sections(self):
        content = "# Chunk Summary\nSomething.\n"
        missing = check_sections(content)
        assert len(missing) == 6  # 7 required - 1 present

    def test_no_sections_at_all(self):
        content = "Just some text without headings."
        missing = check_sections(content)
        assert len(missing) == 7


# ---------------------------------------------------------------------------
# Stale-running reconciliation
# ---------------------------------------------------------------------------

class TestStaleRunning:
    def test_stale_with_valid_result_promotes_to_done(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        # Mark running with old timestamp
        old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        update_chunk_state(status, "chunk-0001", "running")
        status["chunks"]["chunk-0001"]["transitions"][-1]["timestamp"] = old_time

        # Write valid result
        _write_result(run_dir, "chunk-0001")

        resolved = resolve_stale_running(status, manifest, run_dir, timeout_seconds=1800)
        assert "chunk-0001" in resolved
        assert status["chunks"]["chunk-0001"]["state"] == "done"

    def test_stale_without_result_fails(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        update_chunk_state(status, "chunk-0001", "running")
        status["chunks"]["chunk-0001"]["transitions"][-1]["timestamp"] = old_time

        resolved = resolve_stale_running(status, manifest, run_dir, timeout_seconds=1800)
        assert "chunk-0001" in resolved
        assert status["chunks"]["chunk-0001"]["state"] == "failed"
        assert "interrupted_or_stale" in status["chunks"]["chunk-0001"]["last_error"]["code"]

    def test_not_stale_yet_stays_running(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "running")
        # Recent timestamp — not stale yet

        resolved = resolve_stale_running(status, manifest, run_dir, timeout_seconds=1800)
        assert resolved == []
        assert status["chunks"]["chunk-0001"]["state"] == "running"


# ---------------------------------------------------------------------------
# Mark operations
# ---------------------------------------------------------------------------

class TestMarkChunk:
    def test_mark_failed_with_reason(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        mark_chunk(status, "chunk-0001", "failed", reason="bad output", run_dir=run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "failed"
        assert status["chunks"]["chunk-0001"]["reason"] == "bad output"
        assert status["chunks"]["chunk-0001"]["last_error"]["code"] == "manual_mark"

    def test_mark_skipped_with_reason(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        mark_chunk(status, "chunk-0001", "skipped", reason="not relevant", run_dir=run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "skipped"
        assert status["chunks"]["chunk-0001"]["reason"] == "not relevant"

    def test_mark_failed_requires_reason(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        with pytest.raises(ValueError, match="--reason is required"):
            mark_chunk(status, "chunk-0001", "failed", run_dir=run_dir)

    def test_mark_done_requires_valid_result(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        with pytest.raises(ValueError, match="result validation failed"):
            mark_chunk(status, "chunk-0001", "done", run_dir=run_dir)

    def test_mark_done_with_valid_result(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        _write_result(run_dir, "chunk-0001")
        mark_chunk(status, "chunk-0001", "done", run_dir=run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "done"

    def test_mark_unknown_chunk(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        with pytest.raises(ValueError, match="Unknown chunk"):
            mark_chunk(status, "chunk-9999", "failed", reason="test")

    def test_mark_pending(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "failed")
        mark_chunk(status, "chunk-0001", "pending", run_dir=run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "pending"


# ---------------------------------------------------------------------------
# Retry operations
# ---------------------------------------------------------------------------

class TestRetryChunks:
    def test_retry_failed_chunks(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "failed")
        update_chunk_state(status, "chunk-0002", "failed")

        reset = retry_chunks(status, manifest)
        assert set(reset) == {"chunk-0001", "chunk-0002"}
        assert status["chunks"]["chunk-0001"]["state"] == "pending"
        assert status["chunks"]["chunk-0002"]["state"] == "pending"

    def test_retry_respects_max_attempts(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "failed")
        # Add 3 fake attempts to exceed max_attempts
        status["chunks"]["chunk-0001"]["attempts"] = [
            {"attempt": 1, "state": "failed"},
            {"attempt": 2, "state": "failed"},
            {"attempt": 3, "state": "failed"},
        ]

        reset = retry_chunks(status, manifest)
        assert reset == []  # max_attempts reached

    def test_retry_force_overrides_max(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "failed")
        status["chunks"]["chunk-0001"]["attempts"] = [
            {"attempt": 1, "state": "failed"},
            {"attempt": 2, "state": "failed"},
            {"attempt": 3, "state": "failed"},
        ]

        reset = retry_chunks(status, manifest, force=True)
        assert "chunk-0001" in reset

    def test_retry_specific_chunks(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "failed")
        update_chunk_state(status, "chunk-0002", "failed")

        reset = retry_chunks(status, manifest, chunk_ids=["chunk-0001"])
        assert reset == ["chunk-0001"]
        assert status["chunks"]["chunk-0002"]["state"] == "failed"

    def test_retry_preserves_attempt_history(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "failed")
        status["chunks"]["chunk-0001"]["attempts"] = [
            {"attempt": 1, "state": "failed"},
        ]

        retry_chunks(status, manifest)
        # Attempts list should still be there
        assert len(status["chunks"]["chunk-0001"]["attempts"]) == 1

    def test_retry_skipped_chunks(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "skipped")
        reset = retry_chunks(status, manifest)
        assert "chunk-0001" in reset


# ---------------------------------------------------------------------------
# Skip operations
# ---------------------------------------------------------------------------

class TestSkipChunk:
    def test_skip_with_reason(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        skip_chunk(status, "chunk-0001", "not relevant")
        assert status["chunks"]["chunk-0001"]["state"] == "skipped"
        assert status["chunks"]["chunk-0001"]["reason"] == "not relevant"

    def test_skip_requires_reason(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        with pytest.raises(ValueError, match="--reason is required"):
            skip_chunk(status, "chunk-0001", "")

    def test_skip_unknown_chunk(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        with pytest.raises(ValueError, match="Unknown chunk"):
            skip_chunk(status, "chunk-9999", "reason")


# ---------------------------------------------------------------------------
# Reconciliation V3
# ---------------------------------------------------------------------------

class TestReconcileV3:
    def test_running_with_result_promotes_to_done(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "running")
        save_status(status, run_dir)
        _write_result(run_dir, "chunk-0001")

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "done"

    def test_missing_with_result_promotes_to_done(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "missing")
        save_status(status, run_dir)
        _write_result(run_dir, "chunk-0001")

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "done"

    def test_done_without_result_demotes_to_missing(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "done")
        save_status(status, run_dir)
        # No result file on disk

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "missing"

    def test_skipped_preserved_even_with_result(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "skipped")
        save_status(status, run_dir)
        _write_result(run_dir, "chunk-0001")

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "skipped"

    def test_manifest_chunk_missing_from_status(self, tmp_path):
        manifest = _make_manifest(3)
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        # Remove a chunk from status
        del status["chunks"]["chunk-0003"]
        save_status(status, run_dir)

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert "chunk-0003" in status["chunks"]
        assert status["chunks"]["chunk-0003"]["state"] == "pending"


# ---------------------------------------------------------------------------
# Atomic status writes
# ---------------------------------------------------------------------------
# Enhanced V3 reconciliation (spec 12 compliance)
# ---------------------------------------------------------------------------

class TestReconcileV3Enhanced:
    def test_done_with_empty_result_becomes_failed(self, tmp_path):
        """Spec 12: done but result is empty → failed with validation reason."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "done")
        save_status(status, run_dir)
        # Write empty result file
        P.worker_result_path(run_dir, "chunk-0001").write_text("", encoding="utf-8")

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "failed"
        assert status["chunks"]["chunk-0001"]["last_error"]["code"] == "empty_result"

    def test_done_with_whitespace_only_result_becomes_failed(self, tmp_path):
        """Spec 12: done but result is whitespace-only → failed."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "done")
        save_status(status, run_dir)
        P.worker_result_path(run_dir, "chunk-0001").write_text("   \n  \n  ", encoding="utf-8")

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "failed"
        assert status["chunks"]["chunk-0001"]["last_error"]["code"] == "whitespace_only"

    def test_done_with_missing_result_becomes_missing(self, tmp_path):
        """Spec 12: done but result file is missing → missing (unchanged behavior)."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "done")
        save_status(status, run_dir)
        # No result file on disk

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "missing"

    def test_stale_running_resolved_to_failed(self, tmp_path):
        """Spec 12: stale running with no valid result → failed on status read."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        # Fake a running state from 2 hours ago
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        status["chunks"]["chunk-0001"]["state"] = "running"
        status["chunks"]["chunk-0001"]["transitions"].append(
            {"state": "running", "timestamp": two_hours_ago}
        )
        save_status(status, run_dir)

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir, timeout_seconds=1800)
        assert status["chunks"]["chunk-0001"]["state"] == "failed"
        assert status["chunks"]["chunk-0001"]["last_error"]["code"] == "interrupted_or_stale"

    def test_stale_running_with_valid_result_promotes_to_done(self, tmp_path):
        """Spec 12: stale running with valid result → done."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        status["chunks"]["chunk-0001"]["state"] = "running"
        status["chunks"]["chunk-0001"]["transitions"].append(
            {"state": "running", "timestamp": two_hours_ago}
        )
        save_status(status, run_dir)
        _write_result(run_dir, "chunk-0001")

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir, timeout_seconds=1800)
        assert status["chunks"]["chunk-0001"]["state"] == "done"

    def test_recent_running_not_resolved(self, tmp_path):
        """Running chunk within timeout window is not resolved."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        just_now = datetime.now(timezone.utc).isoformat()
        status["chunks"]["chunk-0001"]["state"] = "running"
        status["chunks"]["chunk-0001"]["transitions"].append(
            {"state": "running", "timestamp": just_now}
        )
        save_status(status, run_dir)

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir, timeout_seconds=1800)
        assert status["chunks"]["chunk-0001"]["state"] == "running"

    def test_unknown_chunks_in_status_reported(self, tmp_path):
        """Spec 12: unknown chunks in status → reported without crashing."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        # Add an extra chunk that's not in manifest
        status["chunks"]["chunk-9999"] = {
            "state": "done",
            "transitions": [{"state": "done", "timestamp": datetime.now(timezone.utc).isoformat()}],
        }
        save_status(status, run_dir)

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        # Should not crash and should report the unknown chunk
        assert "_warnings" in status
        assert any("chunk-9999" in w for w in status["_warnings"])
        # Original chunks still intact
        for c in manifest["chunks"]:
            assert c["id"] in status["chunks"]

    def test_unknown_chunk_warnings_not_duplicated(self, tmp_path):
        """Calling reconcile twice doesn't duplicate warnings."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        status["chunks"]["chunk-9999"] = {
            "state": "pending",
            "transitions": [{"state": "pending", "timestamp": datetime.now(timezone.utc).isoformat()}],
        }
        save_status(status, run_dir)

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert len([w for w in status["_warnings"] if "chunk-9999" in w]) == 1


# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_status_write_no_tmp_left(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        save_status(status, run_dir)

        # No .tmp file should remain
        assert not P.status_path(run_dir).with_suffix(".tmp").exists()
        # status.json should exist and be valid
        loaded = load_status(run_dir)
        assert loaded is not None
        assert loaded["run_state"] == "ingested"


# ---------------------------------------------------------------------------
# V2 status lazy upgrade
# ---------------------------------------------------------------------------

class TestV2StatusLazyUpgrade:
    def test_v2_status_loads_cleanly(self, tmp_path):
        """V2 status files without attempts/reasons load and work."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        # V2 status has no 'attempts' key — that's fine
        assert "attempts" not in status["chunks"]["chunk-0001"]

        # Operations should still work
        update_chunk_state(status, "chunk-0001", "done")
        assert status["chunks"]["chunk-0001"]["state"] == "done"

    def test_v2_reconcile_works(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)

        # Write result manually
        _write_result(run_dir, "chunk-0001")

        status = load_status(run_dir)
        status = reconcile_status(status, manifest, run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "done"


# ---------------------------------------------------------------------------
# Summarize failures
# ---------------------------------------------------------------------------

class TestSummarizeFailures:
    def test_no_failures(self, tmp_path):
        manifest = _make_manifest()
        status = create_status(manifest)
        problems = summarize_failures(status)
        assert problems == []

    def test_failed_chunks_reported(self, tmp_path):
        manifest = _make_manifest()
        status = create_status(manifest)
        update_chunk_state(status, "chunk-0001", "failed")
        status["chunks"]["chunk-0001"]["last_error"] = {
            "code": "test",
            "message": "test error",
        }

        problems = summarize_failures(status)
        assert len(problems) == 1
        assert problems[0]["chunk_id"] == "chunk-0001"
        assert problems[0]["state"] == "failed"
        assert problems[0]["last_error"]["message"] == "test error"

    def test_skipped_and_missing_reported(self, tmp_path):
        manifest = _make_manifest()
        status = create_status(manifest)
        update_chunk_state(status, "chunk-0001", "skipped")
        status["chunks"]["chunk-0001"]["reason"] = "not needed"
        update_chunk_state(status, "chunk-0002", "missing")

        problems = summarize_failures(status)
        assert len(problems) == 2
        states = {p["state"] for p in problems}
        assert states == {"skipped", "missing"}


# ---------------------------------------------------------------------------
# Max attempts
# ---------------------------------------------------------------------------

class TestMaxAttempts:
    def test_default_max_attempts(self):
        manifest = _make_manifest()
        assert get_max_attempts(manifest) == 3

    def test_custom_max_attempts(self):
        manifest = _make_manifest()
        manifest["executor"] = {"max_attempts": 5}
        assert get_max_attempts(manifest) == 5


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCLIMark:
    def test_mark_failed(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        main(["mark", str(run_dir), cid, "failed", "--reason", "bad output"])

        status = load_status(run_dir)
        assert status["chunks"][cid]["state"] == "failed"

    def test_mark_skipped(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        main(["mark", str(run_dir), cid, "skipped", "--reason", "not relevant"])

        status = load_status(run_dir)
        assert status["chunks"][cid]["state"] == "skipped"

    def test_mark_failed_no_reason_fails(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        try:
            main(["mark", str(run_dir), cid, "failed"])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1


class TestCLIRetry:
    def test_retry_failed(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        main(["mark", str(run_dir), cid, "failed", "--reason", "bad"])
        main(["retry", str(run_dir), "--failed"])

        status = load_status(run_dir)
        assert status["chunks"][cid]["state"] == "pending"

    def test_retry_specific_chunk(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        main(["mark", str(run_dir), cid, "failed", "--reason", "bad"])
        main(["retry", str(run_dir), "--chunk", cid])

        status = load_status(run_dir)
        assert status["chunks"][cid]["state"] == "pending"


class TestCLISkip:
    def test_skip(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        main(["skip", str(run_dir), cid, "--reason", "not needed"])

        status = load_status(run_dir)
        assert status["chunks"][cid]["state"] == "skipped"


class TestCLIStatusFailures:
    def test_status_failures_flag(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        main(["mark", str(run_dir), cid, "failed", "--reason", "test failure"])
        capsys.readouterr()  # clear

        try:
            main(["status", str(run_dir), "--failures"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert cid in captured.out
        assert "failed" in captured.out

    def test_status_failures_json(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        main(["mark", str(run_dir), cid, "failed", "--reason", "test failure"])
        capsys.readouterr()

        try:
            main(["status", str(run_dir), "--failures", "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        problems = json.loads(captured.out)
        assert len(problems) >= 1
        assert any(p["chunk_id"] == cid for p in problems)


# ---------------------------------------------------------------------------
# Event logging for mark/retry/skip CLI operations
# ---------------------------------------------------------------------------

class TestMarkRetrySkipEvents:
    """Verify mark, retry, and skip CLI commands emit events."""

    def test_mark_emits_event(self, tmp_path, source_file, capsys):
        from gutenberg.reporting import read_events
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])
        capsys.readouterr()

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        main(["mark", str(run_dir), cid, "failed", "--reason", "test failure"])

        events = read_events(run_dir)
        mark_events = [e for e in events if e["event"] == "chunk_marked"]
        assert len(mark_events) == 1
        assert mark_events[0]["chunk_id"] == cid
        assert mark_events[0]["state"] == "failed"

    def test_skip_emits_event(self, tmp_path, source_file, capsys):
        from gutenberg.reporting import read_events
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])
        capsys.readouterr()

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        main(["skip", str(run_dir), cid, "--reason", "not needed"])

        events = read_events(run_dir)
        skip_events = [e for e in events if e["event"] == "chunk_skipped"]
        assert len(skip_events) == 1
        assert skip_events[0]["chunk_id"] == cid
        assert skip_events[0]["reason"] == "not needed"

    def test_retry_emits_events(self, tmp_path, source_file, capsys):
        from gutenberg.reporting import read_events
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])
        capsys.readouterr()

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]

        # First mark as failed
        main(["mark", str(run_dir), cid, "failed", "--reason", "test"])
        # Then retry
        main(["retry", str(run_dir), "--chunk", cid])

        events = read_events(run_dir)
        retry_events = [e for e in events if e["event"] == "chunk_retried"]
        assert len(retry_events) == 1
        assert retry_events[0]["chunk_id"] == cid
