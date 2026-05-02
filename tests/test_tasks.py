"""Tests for per-chunk task materialization (Spec 14)."""

import json
from pathlib import Path

import pytest

from gutenberg.tasks import (
    generate_worker_task,
    generate_synthesis_task,
    build_task_index,
    materialize_tasks,
    check_staleness,
)
from gutenberg.cli import main
from gutenberg import paths as P


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_manifest(num_chunks: int = 3, title: str = "Test Book", author: str = "Test Author") -> dict:
    """Build a minimal manifest dict for testing."""
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
            "prev_context": f"end of chunk {i}" if i > 0 else "",
            "next_context": f"start of chunk {i + 2}" if i < num_chunks - 1 else "",
        })
    # Add inferred_section to first chunk only
    if chunks:
        chunks[0]["inferred_section"] = "Chapter 1"

    return {
        "schema_version": "1.0",
        "source": {"title": title, "author": author},
        "settings": {"chunk_size": 50000, "overlap": 2000},
        "chunks": chunks,
        "results": {"directory": "results"},
        "prompts": {
            "orchestrator": "prompts/orchestrator.md",
            "worker": "prompts/worker.md",
            "synthesis": "prompts/synthesis.md",
        },
    }


def _make_status(manifest: dict, states: dict[str, str] | None = None) -> dict:
    """Build a status dict from manifest. Override per-chunk states via *states*."""
    chunk_statuses = {}
    for c in manifest["chunks"]:
        cid = c["id"]
        state = (states or {}).get(cid, "pending")
        chunk_statuses[cid] = {
            "state": state,
            "transitions": [{"state": state, "timestamp": "2026-01-01T00:00:00+00:00"}],
        }
    return {
        "run_state": "ingested",
        "chunks": chunk_statuses,
        "summary": {"total": len(manifest["chunks"])},
    }


def _setup_run_dir(tmp_path: Path, manifest: dict, status: dict | None = None) -> Path:
    """Create a minimal run directory with manifest, chunks, prompts, results."""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir(parents=True)
    P.chunks_dir(run_dir).mkdir()
    P.prompts_dir(run_dir).mkdir()
    P.results_dir(run_dir).mkdir()

    # Write manifest
    with open(P.manifest_path(run_dir), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    # Write dummy chunk files
    for c in manifest["chunks"]:
        (run_dir / c["path"]).write_text(f"# Chunk content for {c['id']}\n", encoding="utf-8")

    # Write dummy prompt files
    P.orchestrator_prompt_path(run_dir).write_text("orchestrator\n")
    P.worker_prompt_path(run_dir).write_text("worker\n")
    P.synthesis_prompt_path(run_dir).write_text("synthesis\n")

    # Write source
    P.source_path(run_dir).write_text("source text\n")

    # Write status if provided
    if status is not None:
        with open(P.status_path(run_dir), "w") as f:
            json.dump(status, f, indent=2)
            f.write("\n")

    return run_dir


# ---------------------------------------------------------------------------
# Worker task generation tests
# ---------------------------------------------------------------------------

class TestGenerateWorkerTask:
    def test_concrete_values_no_placeholders(self):
        manifest = _make_manifest()
        chunk = manifest["chunks"][0]
        task = generate_worker_task(manifest, chunk, "my-run")

        # Must not contain these placeholders
        for ph in ("{chunk_id}", "{chunk_number}", "{total_chunks}", "{chunk_path}", "{result_path}"):
            assert ph not in task, f"Found placeholder {ph} in worker task"

    def test_all_metadata_present(self):
        manifest = _make_manifest()
        chunk = manifest["chunks"][0]
        task = generate_worker_task(manifest, chunk, "my-run")

        assert "chunk-0001" in task
        assert "Chunk 1 of 3" in task
        assert "chunks/chunk-0001.md" in task
        assert "results/chunk-0001.analysis.md" in task
        assert "Test Book" in task
        assert "Test Author" in task
        assert "my-run" in task
        assert "manifest.json" in task

    def test_inferred_section_included(self):
        manifest = _make_manifest()
        chunk = manifest["chunks"][0]
        task = generate_worker_task(manifest, chunk, "my-run")
        assert "Chapter 1" in task

    def test_inferred_section_absent_when_not_set(self):
        manifest = _make_manifest()
        chunk = manifest["chunks"][1]  # no inferred_section
        task = generate_worker_task(manifest, chunk, "my-run")
        assert "Inferred section" not in task

    def test_prev_context_start_of_text(self):
        manifest = _make_manifest()
        chunk = manifest["chunks"][0]  # first chunk, no prev_context
        task = generate_worker_task(manifest, chunk, "my-run")
        assert "Start of text" in task

    def test_next_context_end_of_text(self):
        manifest = _make_manifest()
        chunk = manifest["chunks"][-1]  # last chunk, no next_context
        task = generate_worker_task(manifest, chunk, "my-run")
        assert "End of text" in task

    def test_middle_chunk_has_both_contexts(self):
        manifest = _make_manifest()
        chunk = manifest["chunks"][1]
        task = generate_worker_task(manifest, chunk, "my-run")
        assert "end of chunk 1" in task
        assert "start of chunk 3" in task

    def test_required_output_format_sections(self):
        manifest = _make_manifest()
        chunk = manifest["chunks"][0]
        task = generate_worker_task(manifest, chunk, "my-run")

        for section in ("# Chunk Summary", "# Key Claims / Ideas", "# Important Quotes",
                        "# Entities / Concepts", "# Open Questions",
                        "# Connections To Other Chunks", "# Synthesis Notes"):
            assert section in task

    def test_untitled_when_no_title(self):
        manifest = _make_manifest(title="", author="")
        chunk = manifest["chunks"][0]
        task = generate_worker_task(manifest, chunk, "my-run")
        assert "Untitled" in task


# ---------------------------------------------------------------------------
# Synthesis task generation tests
# ---------------------------------------------------------------------------

class TestGenerateSynthesisTask:
    def test_full_synthesis_all_done(self):
        manifest = _make_manifest()
        status = _make_status(manifest, {
            "chunk-0001": "done",
            "chunk-0002": "done",
            "chunk-0003": "done",
        })
        task = generate_synthesis_task(manifest, status, "my-run")

        assert "Synthesis Task — Test Book" in task
        assert "[available]" in task
        assert "[missing]" not in task
        assert "[FAILED]" not in task
        assert "Available:** 3 of 3" in task

    def test_partial_marks_gaps(self):
        manifest = _make_manifest()
        status = _make_status(manifest, {
            "chunk-0001": "done",
            "chunk-0002": "failed",
            "chunk-0003": "pending",
        })
        task = generate_synthesis_task(manifest, status, "my-run", partial=True)

        assert "[available]" in task
        assert "[FAILED]" in task
        assert "[missing]" in task
        assert "Partial Synthesis" in task
        assert "chunk-0002" in task
        assert "chunk-0003" in task

    def test_skipped_chunk_shown(self):
        manifest = _make_manifest()
        status = _make_status(manifest, {
            "chunk-0001": "done",
            "chunk-0002": "skipped",
            "chunk-0003": "done",
        })
        task = generate_synthesis_task(manifest, status, "my-run")
        assert "[SKIPPED]" in task

    def test_synthesis_without_status(self):
        manifest = _make_manifest()
        task = generate_synthesis_task(manifest, None, "my-run")
        # All should show as missing since no status
        assert task.count("[missing]") == 3

    def test_synthesis_output_format(self):
        manifest = _make_manifest()
        task = generate_synthesis_task(manifest, None, "my-run")
        for section in ("## Missing Chunks", "## Executive Summary", "## Key Themes",
                        "## Critical Analysis", "## Key Quotes", "## Open Questions"):
            assert section in task


# ---------------------------------------------------------------------------
# Task index tests
# ---------------------------------------------------------------------------

class TestBuildTaskIndex:
    def test_schema_version(self):
        manifest = _make_manifest()
        index = build_task_index(manifest)
        assert index["schema_version"] == "1.0"

    def test_correct_chunk_count(self):
        manifest = _make_manifest(num_chunks=5)
        index = build_task_index(manifest)
        assert len(index["tasks"]["workers"]) == 5

    def test_relative_posix_paths(self):
        manifest = _make_manifest()
        index = build_task_index(manifest)

        for w in index["tasks"]["workers"]:
            assert not w["task_path"].startswith("/")
            assert "\\" not in w["task_path"]
            assert not w["chunk_path"].startswith("/")
            assert not w["result_path"].startswith("/")

        assert not index["tasks"]["synthesis"]["task_path"].startswith("/")
        assert not index["tasks"]["synthesis"]["result_path"].startswith("/")

    def test_worker_fields(self):
        manifest = _make_manifest()
        index = build_task_index(manifest)
        w = index["tasks"]["workers"][0]

        assert w["chunk_id"] == "chunk-0001"
        assert w["chunk_number"] == 1
        assert w["total_chunks"] == 3
        assert w["chunk_path"] == "chunks/chunk-0001.md"
        assert w["task_path"] == "tasks/workers/chunk-0001.worker.md"
        assert w["result_path"] == "results/chunk-0001.analysis.md"

    def test_synthesis_fields(self):
        manifest = _make_manifest()
        index = build_task_index(manifest)
        s = index["tasks"]["synthesis"]

        assert s["task_path"] == "tasks/synthesis.md"
        assert s["result_path"] == "results/synthesis.md"

    def test_valid_json_roundtrip(self):
        manifest = _make_manifest()
        index = build_task_index(manifest)
        text = json.dumps(index, indent=2, sort_keys=True)
        parsed = json.loads(text)
        assert parsed == index


# ---------------------------------------------------------------------------
# Materialization tests
# ---------------------------------------------------------------------------

class TestMaterializeTasks:
    def test_creates_all_files(self, tmp_path):
        manifest = _make_manifest()
        status = _make_status(manifest)
        run_dir = _setup_run_dir(tmp_path, manifest, status)

        result = materialize_tasks(manifest, status, run_dir)

        assert result["written"] == 5  # 3 workers + synthesis + index
        assert result["skipped"] == 0
        assert result["total_files"] == 5
        assert result["worker_count"] == 3

        # Verify files on disk
        assert P.tasks_index_path(run_dir).exists()
        assert P.synthesis_task_path(run_dir).exists()
        for c in manifest["chunks"]:
            assert P.worker_task_path(run_dir, c["id"]).exists()

    def test_idempotent(self, tmp_path):
        manifest = _make_manifest()
        status = _make_status(manifest)
        run_dir = _setup_run_dir(tmp_path, manifest, status)

        materialize_tasks(manifest, status, run_dir)
        result2 = materialize_tasks(manifest, status, run_dir)

        assert result2["written"] == 0
        assert result2["skipped"] == 5

    def test_refresh_rewrites(self, tmp_path):
        manifest = _make_manifest()
        status = _make_status(manifest)
        run_dir = _setup_run_dir(tmp_path, manifest, status)

        materialize_tasks(manifest, status, run_dir)
        result2 = materialize_tasks(manifest, status, run_dir, refresh=True)

        assert result2["written"] == 5
        assert result2["skipped"] == 0

    def test_no_status_works(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run_dir(tmp_path, manifest)

        result = materialize_tasks(manifest, None, run_dir)
        assert result["written"] == 5

    def test_creates_directories(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run_dir(tmp_path, manifest)

        # Ensure tasks dir doesn't exist yet
        assert not P.tasks_dir(run_dir).exists()

        materialize_tasks(manifest, None, run_dir)

        assert P.tasks_workers_dir(run_dir).exists()

    def test_task_file_content_no_placeholders(self, tmp_path):
        manifest = _make_manifest()
        status = _make_status(manifest)
        run_dir = _setup_run_dir(tmp_path, manifest, status)

        materialize_tasks(manifest, status, run_dir)

        placeholders = ("{chunk_id}", "{chunk_number}", "{total_chunks}", "{chunk_path}", "{result_path}")
        for c in manifest["chunks"]:
            content = P.worker_task_path(run_dir, c["id"]).read_text(encoding="utf-8")
            for ph in placeholders:
                assert ph not in content


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_manifest_same_output(self, tmp_path):
        manifest = _make_manifest()
        status = _make_status(manifest)

        run_dir1 = _setup_run_dir(tmp_path / "a", manifest, status)
        run_dir2 = _setup_run_dir(tmp_path / "b", manifest, status)

        # Both have the same run_dir.name since _setup_run_dir uses "test-run"
        materialize_tasks(manifest, status, run_dir1)
        materialize_tasks(manifest, status, run_dir2)

        for c in manifest["chunks"]:
            c1 = P.worker_task_path(run_dir1, c["id"]).read_text(encoding="utf-8")
            c2 = P.worker_task_path(run_dir2, c["id"]).read_text(encoding="utf-8")
            assert c1 == c2, f"Determinism failure for {c['id']}"

        s1 = P.synthesis_task_path(run_dir1).read_text(encoding="utf-8")
        s2 = P.synthesis_task_path(run_dir2).read_text(encoding="utf-8")
        assert s1 == s2

        i1 = P.tasks_index_path(run_dir1).read_text(encoding="utf-8")
        i2 = P.tasks_index_path(run_dir2).read_text(encoding="utf-8")
        assert i1 == i2


# ---------------------------------------------------------------------------
# Staleness tests
# ---------------------------------------------------------------------------

class TestStaleness:
    def test_detects_missing_tasks(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run_dir(tmp_path, manifest)

        stale = check_staleness(manifest, run_dir)
        # 3 workers + synthesis + index = 5 missing
        assert len(stale) == 5
        reasons = {s["reason"] for s in stale}
        assert reasons == {"missing"}

    def test_no_stale_after_materialize(self, tmp_path):
        manifest = _make_manifest()
        status = _make_status(manifest)
        run_dir = _setup_run_dir(tmp_path, manifest, status)

        materialize_tasks(manifest, status, run_dir)
        stale = check_staleness(manifest, run_dir)
        assert len(stale) == 0

    def test_detects_content_change(self, tmp_path):
        manifest = _make_manifest()
        status = _make_status(manifest)
        run_dir = _setup_run_dir(tmp_path, manifest, status)

        materialize_tasks(manifest, status, run_dir)

        # Tamper with a worker task
        task_file = P.worker_task_path(run_dir, "chunk-0001")
        task_file.write_text("tampered content", encoding="utf-8")

        stale = check_staleness(manifest, run_dir)
        assert len(stale) == 1
        assert stale[0]["chunk_id"] == "chunk-0001"
        assert stale[0]["reason"] == "content_changed"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLITasks:
    def test_tasks_default(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        main(["tasks", str(run_dir)])

        assert P.tasks_index_path(run_dir).exists()
        assert P.synthesis_task_path(run_dir).exists()

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        for c in manifest["chunks"]:
            assert P.worker_task_path(run_dir, c["id"]).exists()

    def test_tasks_dry_run(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        main(["tasks", str(run_dir), "--dry-run"])

        # Dry run should NOT create task files
        assert not P.tasks_dir(run_dir).exists()

    def test_tasks_json(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])
        capsys.readouterr()  # clear ingest output

        main(["tasks", str(run_dir), "--json"])

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "written" in result
        assert result["written"] > 0

    def test_tasks_refresh(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        main(["tasks", str(run_dir)])
        main(["tasks", str(run_dir), "--refresh"])

        assert P.tasks_index_path(run_dir).exists()

    def test_tasks_missing_run_dir(self, tmp_path):
        try:
            main(["tasks", str(tmp_path / "nonexistent")])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1

    def test_tasks_no_manifest(self, tmp_path):
        run_dir = tmp_path / "empty-run"
        run_dir.mkdir()
        try:
            main(["tasks", str(run_dir)])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1


# ---------------------------------------------------------------------------
# Validation integration tests
# ---------------------------------------------------------------------------

class TestValidationTaskChecks:
    def test_validation_passes_without_tasks(self, tmp_path, source_file):
        """V2 runs without task files should still pass validation."""
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])
        rc = main(["validate", str(run_dir)])
        # Should not fail (returns None on success, not 0, so just check no SystemExit)

    def test_validation_passes_with_tasks(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])
        main(["tasks", str(run_dir)])
        capsys.readouterr()  # clear prior output

        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass
        captured = capsys.readouterr()
        checks = json.loads(captured.out)
        check_names = {c["check"] for c in checks}

        assert "task_index_valid_json" in check_names
        assert "task_files_exist" in check_names
        assert "task_no_placeholders" in check_names

        for c in checks:
            assert c["passed"], f"Check failed: {c['check']}: {c['detail']}"

    def test_validation_catches_invalid_index(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])

        # Write invalid JSON to task index
        P.tasks_dir(run_dir).mkdir(parents=True, exist_ok=True)
        P.tasks_index_path(run_dir).write_text("not json!", encoding="utf-8")
        capsys.readouterr()  # clear prior output

        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass
        captured = capsys.readouterr()
        checks = json.loads(captured.out)

        index_check = next(c for c in checks if c["check"] == "task_index_valid_json")
        assert not index_check["passed"]

    def test_validation_catches_placeholders(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])
        main(["tasks", str(run_dir)])

        # Write a task file with a placeholder
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]
        task_path = P.worker_task_path(run_dir, cid)
        task_path.write_text("# Bad task with {chunk_id} placeholder\n", encoding="utf-8")
        capsys.readouterr()  # clear prior output

        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass
        captured = capsys.readouterr()
        checks = json.loads(captured.out)

        ph_check = next((c for c in checks if c["check"] == "task_no_placeholders"), None)
        assert ph_check is not None
        assert not ph_check["passed"]
