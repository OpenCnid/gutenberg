"""Tests for run status tracking (spec 07)."""

import json
from datetime import datetime, timezone

import pytest

from gutenberg.chunking import chunk_text
from gutenberg.manifest import build_manifest, write_manifest
from gutenberg.status import (
    CHUNK_STATES,
    RUN_STATES,
    compute_run_state,
    create_status,
    infer_status,
    load_status,
    save_status,
    summarize_status,
    update_chunk_state,
)
from gutenberg.cli import main
from gutenberg import paths as P


def _make_manifest(text="Hello world.\n\nSecond paragraph.\n", **kwargs):
    """Build a manifest dict without writing to disk."""
    chunks = chunk_text(text, **kwargs)
    return build_manifest(
        input_path="/tmp/source.txt",
        source_text=text,
        chunks=chunks,
        chunk_size=kwargs.get("chunk_size", 50_000),
        overlap=kwargs.get("overlap", 2_000),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_run(tmp_path, text="a" * 600, chunk_size=200, overlap=20):
    """Create a run directory via CLI and return (run_dir, manifest)."""
    src = tmp_path / "source.txt"
    src.write_text(text, encoding="utf-8")
    run_dir = tmp_path / "run"
    main(["ingest", str(src), "--out", str(run_dir),
          "--chunk-size", str(chunk_size), "--overlap", str(overlap)])
    manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
    return run_dir, manifest


# ── create_status ─────────────────────────────────────────────────────

class TestCreateStatus:
    def test_all_chunks_pending(self):
        manifest = _make_manifest("a" * 600, chunk_size=200, overlap=20)
        status = create_status(manifest)
        for entry in status["chunks"].values():
            assert entry["state"] == "pending"

    def test_run_state_ingested(self):
        manifest = _make_manifest()
        status = create_status(manifest)
        assert status["run_state"] == "ingested"

    def test_chunk_ids_match_manifest(self):
        manifest = _make_manifest("a" * 600, chunk_size=200, overlap=20)
        status = create_status(manifest)
        manifest_ids = {c["id"] for c in manifest["chunks"]}
        assert set(status["chunks"].keys()) == manifest_ids

    def test_initial_transition_recorded(self):
        manifest = _make_manifest()
        status = create_status(manifest)
        for entry in status["chunks"].values():
            assert len(entry["transitions"]) == 1
            assert entry["transitions"][0]["state"] == "pending"
            # ISO 8601 timestamp
            datetime.fromisoformat(entry["transitions"][0]["timestamp"])

    def test_summary_present(self):
        manifest = _make_manifest("a" * 600, chunk_size=200, overlap=20)
        status = create_status(manifest)
        assert "summary" in status
        assert status["summary"]["total"] == len(manifest["chunks"])
        assert status["summary"]["pending"] == len(manifest["chunks"])
        assert status["summary"]["done"] == 0


# ── update_chunk_state ────────────────────────────────────────────────

class TestUpdateChunkState:
    def test_transitions_correctly(self):
        manifest = _make_manifest()
        status = create_status(manifest)
        cid = list(status["chunks"].keys())[0]
        update_chunk_state(status, cid, "running")
        assert status["chunks"][cid]["state"] == "running"

    def test_records_timestamp(self):
        manifest = _make_manifest()
        status = create_status(manifest)
        cid = list(status["chunks"].keys())[0]
        update_chunk_state(status, cid, "done")
        transitions = status["chunks"][cid]["transitions"]
        assert len(transitions) == 2
        assert transitions[1]["state"] == "done"
        datetime.fromisoformat(transitions[1]["timestamp"])

    def test_invalid_state_raises(self):
        manifest = _make_manifest()
        status = create_status(manifest)
        cid = list(status["chunks"].keys())[0]
        with pytest.raises(ValueError, match="Invalid chunk state"):
            update_chunk_state(status, cid, "bogus")

    def test_updates_run_state(self):
        manifest = _make_manifest()
        status = create_status(manifest)
        cid = list(status["chunks"].keys())[0]
        update_chunk_state(status, cid, "done")
        # Single chunk done → complete
        assert status["run_state"] == "complete"

    def test_updates_summary(self):
        manifest = _make_manifest()
        status = create_status(manifest)
        cid = list(status["chunks"].keys())[0]
        update_chunk_state(status, cid, "done")
        assert status["summary"]["done"] == 1


# ── compute_run_state ─────────────────────────────────────────────────

class TestComputeRunState:
    def test_all_pending_is_ingested(self):
        status = {"chunks": {"a": {"state": "pending"}, "b": {"state": "pending"}}}
        assert compute_run_state(status) == "ingested"

    def test_all_done_is_complete(self):
        status = {"chunks": {"a": {"state": "done"}, "b": {"state": "done"}}}
        assert compute_run_state(status) == "complete"

    def test_mixed_done_pending_is_in_progress(self):
        status = {"chunks": {"a": {"state": "done"}, "b": {"state": "pending"}}}
        assert compute_run_state(status) == "in_progress"

    def test_done_and_failed_is_partial(self):
        status = {"chunks": {"a": {"state": "done"}, "b": {"state": "failed"}}}
        assert compute_run_state(status) == "partial"

    def test_done_and_missing_is_partial(self):
        status = {"chunks": {"a": {"state": "done"}, "b": {"state": "missing"}}}
        assert compute_run_state(status) == "partial"

    def test_running_is_in_progress(self):
        status = {"chunks": {"a": {"state": "running"}, "b": {"state": "pending"}}}
        assert compute_run_state(status) == "in_progress"

    def test_empty_is_ingested(self):
        status = {"chunks": {}}
        assert compute_run_state(status) == "ingested"


# ── save / load round-trip ────────────────────────────────────────────

class TestSaveLoad:
    def test_round_trip(self, tmp_path):
        manifest = _make_manifest("a" * 600, chunk_size=200, overlap=20)
        status = create_status(manifest)
        save_status(status, tmp_path)
        loaded = load_status(tmp_path)
        assert loaded == status

    def test_load_returns_none_when_absent(self, tmp_path):
        assert load_status(tmp_path) is None

    def test_saved_file_is_valid_json(self, tmp_path):
        manifest = _make_manifest()
        status = create_status(manifest)
        path = save_status(status, tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["run_state"] == "ingested"


# ── infer_status (V1 compat) ─────────────────────────────────────────

class TestInferStatus:
    def test_no_results_all_pending(self, tmp_path):
        manifest = _make_manifest("a" * 600, chunk_size=200, overlap=20)
        # Create results dir but no result files
        P.results_dir(tmp_path).mkdir(parents=True)
        status = infer_status(manifest, tmp_path)
        for entry in status["chunks"].values():
            assert entry["state"] == "pending"
        assert status["run_state"] == "ingested"

    def test_result_file_marks_done(self, tmp_path):
        manifest = _make_manifest("a" * 600, chunk_size=200, overlap=20)
        P.results_dir(tmp_path).mkdir(parents=True)
        # Place a non-empty result for first chunk
        cid = manifest["chunks"][0]["id"]
        P.worker_result_path(tmp_path, cid).write_text("Analysis result.\n", encoding="utf-8")
        status = infer_status(manifest, tmp_path)
        assert status["chunks"][cid]["state"] == "done"

    def test_empty_result_stays_pending(self, tmp_path):
        manifest = _make_manifest("a" * 600, chunk_size=200, overlap=20)
        P.results_dir(tmp_path).mkdir(parents=True)
        cid = manifest["chunks"][0]["id"]
        P.worker_result_path(tmp_path, cid).write_text("", encoding="utf-8")
        status = infer_status(manifest, tmp_path)
        assert status["chunks"][cid]["state"] == "pending"

    def test_timestamps_are_iso(self, tmp_path):
        manifest = _make_manifest()
        P.results_dir(tmp_path).mkdir(parents=True)
        status = infer_status(manifest, tmp_path)
        for entry in status["chunks"].values():
            datetime.fromisoformat(entry["transitions"][0]["timestamp"])


# ── summarize_status ──────────────────────────────────────────────────

class TestSummarizeStatus:
    def test_counts_correct(self):
        manifest = _make_manifest("a" * 600, chunk_size=200, overlap=20)
        status = create_status(manifest)
        cids = list(status["chunks"].keys())
        update_chunk_state(status, cids[0], "done")
        summary = summarize_status(status)
        assert summary["done"] == 1
        assert summary["pending"] == len(cids) - 1
        assert summary["total"] == len(cids)
        assert summary["run_state"] == status["run_state"]


# ── CLI integration ──────────────────────────────────────────────────

class TestStatusCLI:
    def test_status_on_fresh_run(self, tmp_path, capsys):
        run_dir, manifest = _make_run(tmp_path)
        try:
            main(["status", str(run_dir)])
        except SystemExit as e:
            assert e.code == 1  # not complete
        output = capsys.readouterr().out
        assert "pending" in output
        assert "ingested" in output

    def test_status_json(self, tmp_path, capsys):
        run_dir, manifest = _make_run(tmp_path)
        capsys.readouterr()  # discard ingest output
        try:
            main(["status", str(run_dir), "--json"])
        except SystemExit as e:
            assert e.code == 1
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["run_state"] == "ingested"
        assert data["total"] > 0

    def test_status_after_result(self, tmp_path, capsys):
        run_dir, manifest = _make_run(tmp_path)
        # Write result for all chunks → complete
        for c in manifest["chunks"]:
            P.worker_result_path(run_dir, c["id"]).write_text(
                "Result.\n", encoding="utf-8"
            )
        # Update status.json
        from gutenberg.status import load_status as _ls, save_status as _ss, update_chunk_state as _uc
        status = _ls(run_dir)
        for c in manifest["chunks"]:
            _uc(status, c["id"], "done")
        _ss(status, run_dir)

        main(["status", str(run_dir)])  # exit 0 — complete
        output = capsys.readouterr().out
        assert "complete" in output

    def test_status_exit_0_when_complete(self, tmp_path):
        run_dir, manifest = _make_run(tmp_path)
        from gutenberg.status import load_status as _ls, save_status as _ss, update_chunk_state as _uc
        status = _ls(run_dir)
        for c in manifest["chunks"]:
            P.worker_result_path(run_dir, c["id"]).write_text("Result.\n", encoding="utf-8")
            _uc(status, c["id"], "done")
        _ss(status, run_dir)
        # Should not raise SystemExit or raise with code 0
        main(["status", str(run_dir)])

    def test_status_exit_1_when_incomplete(self, tmp_path):
        run_dir, _ = _make_run(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(["status", str(run_dir)])
        assert exc_info.value.code == 1

    def test_v1_run_without_status_json(self, tmp_path, capsys):
        """V1 run (no status.json) produces valid inferred status."""
        run_dir, manifest = _make_run(tmp_path)
        # Remove status.json to simulate V1
        P.status_path(run_dir).unlink()
        try:
            main(["status", str(run_dir)])
        except SystemExit:
            pass
        output = capsys.readouterr().out
        assert "pending" in output

    def test_status_json_on_v1_run(self, tmp_path, capsys):
        """V1 run --json still outputs valid JSON."""
        run_dir, manifest = _make_run(tmp_path)
        P.status_path(run_dir).unlink()
        # Place one result
        cid = manifest["chunks"][0]["id"]
        P.worker_result_path(run_dir, cid).write_text("Analysis.\n", encoding="utf-8")
        capsys.readouterr()  # discard ingest output
        try:
            main(["status", str(run_dir), "--json"])
        except SystemExit:
            pass
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["done"] >= 1

    def test_status_created_during_ingest(self, tmp_path):
        run_dir, _ = _make_run(tmp_path)
        assert P.status_path(run_dir).exists()
        data = json.loads(P.status_path(run_dir).read_text(encoding="utf-8"))
        assert data["run_state"] == "ingested"

    def test_status_missing_run_dir(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            main(["status", str(tmp_path / "nonexistent")])
        assert exc_info.value.code == 1

    def test_status_missing_manifest(self, tmp_path):
        run_dir = tmp_path / "empty_run"
        run_dir.mkdir()
        with pytest.raises(SystemExit) as exc_info:
            main(["status", str(run_dir)])
        assert exc_info.value.code == 1
