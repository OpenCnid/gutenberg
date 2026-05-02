"""Tests for run artifacts, logs, and reporting (Spec 15)."""

import json
from pathlib import Path

import pytest

from gutenberg.reporting import (
    append_event,
    read_events,
    build_orchestration_summary,
    write_orchestration_summary,
    build_report,
    format_report_markdown,
    format_report_json,
    write_reports,
)
from gutenberg.status import (
    create_status,
    load_status,
    save_status,
    update_chunk_state,
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
        "source": {
            "title": "Test Book",
            "author": "Test Author",
            "char_count": 150000,
        },
        "settings": {"chunk_size": 50000, "overlap": 2000},
        "chunks": chunks,
        "results": {"directory": "results"},
        "prompts": {
            "orchestrator": "prompts/orchestrator.md",
            "worker": "prompts/worker.md",
            "synthesis": "prompts/synthesis.md",
        },
    }


def _setup_run(tmp_path: Path, manifest: dict) -> Path:
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

    status = create_status(manifest)
    save_status(status, run_dir)
    return run_dir


# ---------------------------------------------------------------------------
# Event log tests
# ---------------------------------------------------------------------------

class TestEventLog:
    def test_append_event(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)

        append_event(run_dir, {
            "event": "worker_started",
            "chunk_id": "chunk-0001",
            "attempt": 1,
        })

        events = read_events(run_dir)
        assert len(events) == 1
        assert events[0]["event"] == "worker_started"
        assert events[0]["chunk_id"] == "chunk-0001"
        assert "timestamp" in events[0]

    def test_event_ordering(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)

        for i in range(5):
            append_event(run_dir, {"event": f"event_{i}", "order": i})

        events = read_events(run_dir)
        assert len(events) == 5
        for i, ev in enumerate(events):
            assert ev["order"] == i

    def test_valid_jsonl(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)

        append_event(run_dir, {"event": "test1"})
        append_event(run_dir, {"event": "test2"})

        events_path = P.logs_dir(run_dir) / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert "event" in parsed

    def test_empty_events(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)

        events = read_events(run_dir)
        assert events == []


# ---------------------------------------------------------------------------
# Orchestration summary tests
# ---------------------------------------------------------------------------

class TestOrchestrationSummary:
    def test_correct_fields(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        summary = build_orchestration_summary(manifest, status, run_dir)

        assert summary["schema_version"] == "1.0"
        assert summary["created_by"] == "gutenberg"
        assert "workers" in summary
        assert summary["workers"]["total"] == 3
        assert "synthesis" in summary

    def test_with_executor_config(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        config = {"type": "command", "model": "gpt-5.5", "concurrency": 2}
        summary = build_orchestration_summary(manifest, status, run_dir, config)

        assert summary["executor"]["type"] == "command"
        assert summary["executor"]["model"] == "gpt-5.5"
        assert summary["executor"]["concurrency"] == 2

    def test_write_orchestration(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        path = write_orchestration_summary(manifest, status, run_dir)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# Report tests
# ---------------------------------------------------------------------------

class TestBuildReport:
    def test_full_run_report(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        # Mark all done
        for c in manifest["chunks"]:
            P.worker_result_path(run_dir, c["id"]).write_text(f"# Done\n")
            update_chunk_state(status, c["id"], "done")
        save_status(status, run_dir)

        report = build_report(manifest, status, run_dir)

        assert report["source"]["title"] == "Test Book"
        assert report["source"]["author"] == "Test Author"
        assert report["chunks"]["total"] == 3
        assert report["chunks"]["done"] == 3
        assert report["run_state"] == "complete"

    def test_v1_run_report(self, tmp_path):
        """Reports work for V1 runs without V3 artifacts."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        report = build_report(manifest, status, run_dir)
        assert report["source"]["title"] == "Test Book"
        assert report["chunks"]["pending"] == 3

    def test_partial_run_report(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        P.worker_result_path(run_dir, "chunk-0001").write_text("# Done\n")
        update_chunk_state(status, "chunk-0001", "done")
        update_chunk_state(status, "chunk-0002", "failed")
        status["chunks"]["chunk-0002"]["last_error"] = {"code": "test", "message": "test error"}
        update_chunk_state(status, "chunk-0003", "skipped")
        status["chunks"]["chunk-0003"]["reason"] = "not needed"
        save_status(status, run_dir)

        report = build_report(manifest, status, run_dir)
        assert report["chunks"]["done"] == 1
        assert report["chunks"]["failed"] == 1
        assert report["chunks"]["skipped"] == 1
        assert len(report["failures"]) == 2  # failed + skipped

    def test_report_with_orchestration(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        config = {"type": "command", "model": "gpt-5.5"}
        write_orchestration_summary(manifest, status, run_dir, config)

        report = build_report(manifest, status, run_dir)
        assert "executor" in report
        assert report["executor"]["type"] == "command"


class TestFormatReport:
    def test_markdown_sections(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        report = build_report(manifest, status, run_dir)
        md = format_report_markdown(report)

        assert "# Run Report" in md
        assert "## Source" in md
        assert "## Chunks" in md
        assert "## Synthesis" in md
        assert "Test Book" in md
        assert "Test Author" in md

    def test_json_valid(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        report = build_report(manifest, status, run_dir)
        j = format_report_json(report)
        # Should be serializable
        text = json.dumps(j, indent=2)
        parsed = json.loads(text)
        assert parsed == j


class TestWriteReports:
    def test_writes_both_files(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        report = build_report(manifest, status, run_dir)
        md_path, json_path = write_reports(report, run_dir)

        assert md_path.exists()
        assert json_path.exists()
        assert "# Run Report" in md_path.read_text(encoding="utf-8")
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["source"]["title"] == "Test Book"

    def test_v1_run_reports(self, tmp_path):
        """Write reports for a V1 run without V3 artifacts."""
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        report = build_report(manifest, status, run_dir)
        md_path, json_path = write_reports(report, run_dir)
        assert md_path.exists()
        assert json_path.exists()


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCLIReport:
    def test_report_default(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])
        capsys.readouterr()

        main(["report", str(run_dir)])
        captured = capsys.readouterr()
        assert "# Run Report" in captured.out

    def test_report_json(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])
        capsys.readouterr()

        main(["report", str(run_dir), "--json"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "source" in result
        assert "chunks" in result

    def test_report_write(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])

        main(["report", str(run_dir), "--write"])
        assert P.report_md_path(run_dir).exists()
        assert P.report_json_path(run_dir).exists()

    def test_report_include_validation(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])
        capsys.readouterr()

        main(["report", str(run_dir), "--json", "--include-validation"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "validation" in result

    def test_report_missing_dir(self, tmp_path):
        try:
            main(["report", str(tmp_path / "nonexistent")])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1


# ---------------------------------------------------------------------------
# Validation integration
# ---------------------------------------------------------------------------

class TestValidationArtifacts:
    def test_validation_orchestration_json(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        status = load_status(run_dir)
        write_orchestration_summary(manifest, status, run_dir)
        capsys.readouterr()

        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        checks = json.loads(captured.out)
        orch_check = next((c for c in checks if c["check"] == "orchestration_json_valid"), None)
        assert orch_check is not None
        assert orch_check["passed"]

    def test_validation_report_json(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])
        main(["report", str(run_dir), "--write"])
        capsys.readouterr()

        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        checks = json.loads(captured.out)
        report_check = next((c for c in checks if c["check"] == "report_json_valid"), None)
        assert report_check is not None
        assert report_check["passed"]
