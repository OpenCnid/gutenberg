"""Tests for synthesis execution (Spec 13)."""

import json
import stat
from pathlib import Path

import pytest

from gutenberg.synthesis import (
    check_synthesis_readiness,
    build_synthesis_inputs,
    execute_synthesis,
)
from gutenberg.status import (
    create_status,
    load_status,
    save_status,
    update_chunk_state,
)
from gutenberg.executor import CommandExecutor, ManualExecutor
from gutenberg.tasks import materialize_tasks
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


def _setup_run(tmp_path: Path, manifest: dict, all_done: bool = False) -> Path:
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
    if all_done:
        for c in manifest["chunks"]:
            cid = c["id"]
            P.worker_result_path(run_dir, cid).write_text(f"# Analysis of {cid}\n")
            update_chunk_state(status, cid, "done")
    save_status(status, run_dir)
    return run_dir


def _make_synth_script(tmp_path: Path) -> Path:
    """Create a script that copies staging content to result path."""
    content = "# Synthesis\n\n## Executive Summary\n\nGreat book.\n"
    staging = tmp_path / "_synth_content.md"
    staging.write_text(content, encoding="utf-8")
    script = tmp_path / "synth-worker.sh"
    script.write_text(f'#!/bin/bash\ncp "{staging}" "$1"\n', encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _make_failing_synth_script(tmp_path: Path) -> Path:
    script = tmp_path / "fail-synth.sh"
    script.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


# ---------------------------------------------------------------------------
# Readiness tests
# ---------------------------------------------------------------------------

class TestCheckReadiness:
    def test_all_done_is_ready(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        readiness = check_synthesis_readiness(manifest, status, run_dir)
        assert readiness["ready"]
        assert readiness["available_results"] == 3
        assert readiness["blockers"] == []

    def test_pending_is_blocked(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        readiness = check_synthesis_readiness(manifest, status, run_dir)
        assert not readiness["ready"]
        assert any("pending" in b for b in readiness["blockers"])

    def test_failed_is_blocked(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)
        update_chunk_state(status, "chunk-0001", "failed")
        save_status(status, run_dir)

        readiness = check_synthesis_readiness(manifest, status, run_dir)
        assert not readiness["ready"]
        assert any("failed" in b for b in readiness["blockers"])

    def test_skipped_is_blocked(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)
        update_chunk_state(status, "chunk-0001", "skipped")
        save_status(status, run_dir)

        readiness = check_synthesis_readiness(manifest, status, run_dir)
        assert not readiness["ready"]
        assert any("skipped" in b for b in readiness["blockers"])


# ---------------------------------------------------------------------------
# Build synthesis inputs
# ---------------------------------------------------------------------------

class TestBuildInputs:
    def test_order_matches_manifest(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        inputs = build_synthesis_inputs(manifest, status, run_dir)
        assert [i["chunk_id"] for i in inputs] == ["chunk-0001", "chunk-0002", "chunk-0003"]
        assert all(i["available"] for i in inputs)

    def test_unavailable_chunks_marked(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        inputs = build_synthesis_inputs(manifest, status, run_dir)
        assert not any(i["available"] for i in inputs)


# ---------------------------------------------------------------------------
# Execute synthesis
# ---------------------------------------------------------------------------

class TestExecuteSynthesis:
    def test_full_synthesis(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        script = _make_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script), "{result_path}"])

        result = execute_synthesis(manifest, status, run_dir, executor)
        assert result["success"]
        assert result["state"] == "done"
        assert P.synthesis_result_path(run_dir).exists()

    def test_partial_synthesis(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        # Mark one chunk as failed
        update_chunk_state(status, "chunk-0001", "failed")
        save_status(status, run_dir)

        script = _make_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script), "{result_path}"])

        result = execute_synthesis(
            manifest, status, run_dir, executor,
            partial=True,
        )
        assert result["success"]
        assert result["state"] == "partial"
        assert result["partial"]

    def test_refuses_incomplete_without_partial(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)  # all pending
        status = load_status(run_dir)

        executor = ManualExecutor()
        result = execute_synthesis(manifest, status, run_dir, executor)
        assert not result["success"]
        assert result["state"] == "blocked"

    def test_refuses_overwrite_without_force(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        # Write existing synthesis
        P.synthesis_result_path(run_dir).write_text("# Existing synthesis\n")

        executor = ManualExecutor()
        result = execute_synthesis(manifest, status, run_dir, executor)
        assert not result["success"]
        assert "already exists" in result.get("reason", "")

    def test_force_overwrites(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        P.synthesis_result_path(run_dir).write_text("# Old synthesis\n")

        script = _make_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script), "{result_path}"])

        result = execute_synthesis(
            manifest, status, run_dir, executor,
            force=True,
        )
        assert result["success"]

    def test_empty_result_fails(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        # Script that creates empty file
        script = tmp_path / "empty.sh"
        script.write_text('#!/bin/bash\ntouch "$1"\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        executor = CommandExecutor(command=[str(script), "{result_path}"])
        result = execute_synthesis(manifest, status, run_dir, executor)
        assert not result["success"]
        assert result["state"] == "failed"

    def test_records_attempts(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        script = _make_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script), "{result_path}"])

        execute_synthesis(manifest, status, run_dir, executor)

        status = load_status(run_dir)
        assert "synthesis" in status
        assert len(status["synthesis"]["attempts"]) == 1
        assert status["synthesis"]["state"] == "done"

    def test_failed_executor(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        script = _make_failing_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script)])

        result = execute_synthesis(manifest, status, run_dir, executor)
        assert not result["success"]
        assert result["state"] == "failed"

        status = load_status(run_dir)
        assert status["synthesis"]["state"] == "failed"


# ---------------------------------------------------------------------------
# Synthesis status V2 compatibility
# ---------------------------------------------------------------------------

class TestSynthesisStatusCompat:
    def test_v2_status_without_synthesis(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        assert "synthesis" not in status
        readiness = check_synthesis_readiness(manifest, status, run_dir)
        # Should still work
        assert readiness["state"] in ("blocked", "not_started")


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCLISynthesize:
    def test_dry_run(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])
        capsys.readouterr()

        try:
            main(["synthesize", str(run_dir)])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert "NOT READY" in captured.out or "pending" in captured.out.lower()

    def test_execute_full(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))

        # Write fake worker results for all chunks
        for c in manifest["chunks"]:
            P.worker_result_path(run_dir, c["id"]).write_text(
                f"# Analysis of {c['id']}\n", encoding="utf-8"
            )
        # Reconcile status by running status command
        main(["status", str(run_dir)])

        script = _make_synth_script(tmp_path)
        config = {"executor": {"type": "command", "command": [str(script), "{result_path}"]}}
        config_path = tmp_path / "exec.json"
        config_path.write_text(json.dumps(config))
        capsys.readouterr()

        try:
            main(["synthesize", str(run_dir), "--execute",
                  "--executor-config", str(config_path)])
        except SystemExit:
            pass

        assert P.synthesis_result_path(run_dir).exists()

    def test_synthesize_json(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])
        capsys.readouterr()

        try:
            main(["synthesize", str(run_dir), "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "ready" in result


# ---------------------------------------------------------------------------
# Validation integration
# ---------------------------------------------------------------------------

class TestValidationSynthesis:
    def test_validation_synthesis_consistency(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))

        # Write fake results and mark done
        for c in manifest["chunks"]:
            P.worker_result_path(run_dir, c["id"]).write_text(f"# {c['id']}\n")
        main(["status", str(run_dir)])

        # Execute synthesis
        script = _make_synth_script(tmp_path)
        config = {"executor": {"type": "command", "command": [str(script), "{result_path}"]}}
        config_path = tmp_path / "exec.json"
        config_path.write_text(json.dumps(config))

        try:
            main(["synthesize", str(run_dir), "--execute",
                  "--executor-config", str(config_path)])
        except SystemExit:
            pass

        capsys.readouterr()

        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        checks = json.loads(captured.out)
        synth_check = next((c for c in checks if c["check"] == "synthesis_consistency"), None)
        assert synth_check is not None
        assert synth_check["passed"]


# ---------------------------------------------------------------------------
# Event logging and log file integration (spec 15)
# ---------------------------------------------------------------------------

class TestSynthesisEventLogging:
    """Verify synthesis execution emits lifecycle events."""

    def test_events_on_success(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        script = _make_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script), "{result_path}"])

        execute_synthesis(manifest, status, run_dir, executor)

        from gutenberg.reporting import read_events
        events = read_events(run_dir)
        started = [e for e in events if e["event"] == "synthesis_started"]
        done = [e for e in events if e["event"] == "synthesis_done"]
        assert len(started) == 1
        assert len(done) == 1

    def test_events_on_failure(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        script = _make_failing_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script)])

        execute_synthesis(manifest, status, run_dir, executor)

        from gutenberg.reporting import read_events
        events = read_events(run_dir)
        failed = [e for e in events if e["event"] == "synthesis_failed"]
        assert len(failed) == 1


class TestSynthesisLogFiles:
    """Verify per-attempt synthesis log files are written."""

    def test_log_file_on_success(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        script = _make_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script), "{result_path}"])

        execute_synthesis(manifest, status, run_dir, executor)

        log_file = P.synthesis_log_path(run_dir, 1)
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "Synthesis attempt 1" in content

    def test_log_file_on_failure(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        script = _make_failing_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script)])

        execute_synthesis(manifest, status, run_dir, executor)

        log_file = P.synthesis_log_path(run_dir, 1)
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "Success: False" in content

    def test_log_path_recorded_in_status(self, tmp_path):
        manifest = _make_manifest()
        run_dir = _setup_run(tmp_path, manifest, all_done=True)
        status = load_status(run_dir)

        script = _make_synth_script(tmp_path)
        executor = CommandExecutor(command=[str(script), "{result_path}"])

        execute_synthesis(manifest, status, run_dir, executor)

        status = load_status(run_dir)
        assert len(status["synthesis"]["attempts"]) == 1
        assert status["synthesis"]["attempts"][0].get("log_path") is not None
        assert "logs/synthesis/" in status["synthesis"]["attempts"][0]["log_path"]
