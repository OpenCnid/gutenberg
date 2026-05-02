"""Tests for executor / worker launch integration (Spec 11)."""

import json
import os
import stat
from pathlib import Path

import pytest

from gutenberg.executor import (
    CommandExecutor,
    ManualExecutor,
    ExecutorResult,
    load_executor_config,
    validate_executor_config,
    create_executor,
    execute_workers,
)
from gutenberg.status import (
    create_status,
    load_status,
    save_status,
    update_chunk_state,
)
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


def _make_fake_worker_script(tmp_path: Path, content: str = "# Chunk Summary\nAnalysis.\n") -> Path:
    """Create a shell script that writes fixed content to the result path."""
    # Write content to a staging file, script copies it to the result path
    staging = tmp_path / "_worker_content.md"
    staging.write_text(content, encoding="utf-8")
    script = tmp_path / "fake-worker.sh"
    script.write_text(
        f'#!/bin/bash\ncp "{staging}" "$1"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _make_stdout_worker_script(tmp_path: Path, content: str = "# Chunk Summary\nAnalysis.\n") -> Path:
    """Create a shell script that writes fixed content to stdout."""
    staging = tmp_path / "_stdout_content.md"
    staging.write_text(content, encoding="utf-8")
    script = tmp_path / "stdout-worker.sh"
    script.write_text(
        f'#!/bin/bash\ncat "{staging}"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _make_failing_script(tmp_path: Path, exit_code: int = 1) -> Path:
    script = tmp_path / "fail-worker.sh"
    script.write_text(f"#!/bin/bash\nexit {exit_code}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _make_timeout_script(tmp_path: Path) -> Path:
    script = tmp_path / "timeout-worker.sh"
    script.write_text("#!/bin/bash\nsleep 60\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


# ---------------------------------------------------------------------------
# CommandExecutor tests
# ---------------------------------------------------------------------------

class TestCommandExecutor:
    def test_file_mode(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)
        status = create_status(manifest)
        materialize_tasks(manifest, status, run_dir)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
            output_mode="file",
        )

        task_path = str(P.worker_task_path(run_dir, "chunk-0001"))
        result_path = str(P.worker_result_path(run_dir, "chunk-0001"))

        result = executor.launch(task_path, result_path, timeout=30)
        assert result.success
        assert Path(result_path).exists()
        assert Path(result_path).read_text(encoding="utf-8").strip() == "# Chunk Summary\nAnalysis."

    def test_stdout_mode(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)
        status = create_status(manifest)
        materialize_tasks(manifest, status, run_dir)

        script = _make_stdout_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script)],
            output_mode="stdout",
        )

        task_path = str(P.worker_task_path(run_dir, "chunk-0001"))
        result_path = str(P.worker_result_path(run_dir, "chunk-0001"))

        result = executor.launch(task_path, result_path, timeout=30)
        assert result.success
        content = Path(result_path).read_text(encoding="utf-8")
        assert "# Chunk Summary" in content

    def test_nonzero_exit(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)
        status = create_status(manifest)
        materialize_tasks(manifest, status, run_dir)

        script = _make_failing_script(tmp_path)
        executor = CommandExecutor(command=[str(script)])

        task_path = str(P.worker_task_path(run_dir, "chunk-0001"))
        result_path = str(P.worker_result_path(run_dir, "chunk-0001"))

        result = executor.launch(task_path, result_path, timeout=30)
        assert not result.success
        assert result.exit_code == 1

    def test_timeout(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)
        status = create_status(manifest)
        materialize_tasks(manifest, status, run_dir)

        script = _make_timeout_script(tmp_path)
        executor = CommandExecutor(command=[str(script)])

        task_path = str(P.worker_task_path(run_dir, "chunk-0001"))
        result_path = str(P.worker_result_path(run_dir, "chunk-0001"))

        result = executor.launch(task_path, result_path, timeout=1)
        assert not result.success
        assert "timed out" in result.error_message

    def test_missing_binary(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)
        status = create_status(manifest)
        materialize_tasks(manifest, status, run_dir)

        executor = CommandExecutor(command=["/nonexistent/binary"])

        task_path = str(P.worker_task_path(run_dir, "chunk-0001"))
        result_path = str(P.worker_result_path(run_dir, "chunk-0001"))

        result = executor.launch(task_path, result_path, timeout=30)
        assert not result.success
        assert "not found" in result.error_message.lower()


# ---------------------------------------------------------------------------
# ManualExecutor tests
# ---------------------------------------------------------------------------

class TestManualExecutor:
    def test_no_launch(self):
        executor = ManualExecutor()
        result = executor.launch("task.md", "result.md", timeout=30)
        assert not result.success
        assert "manual" in result.error_message.lower()


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestExecutorConfig:
    def test_load_config_from_file(self, tmp_path):
        config_file = tmp_path / "executor.json"
        config_file.write_text(json.dumps({
            "executor": {
                "type": "command",
                "command": ["echo", "hello"],
                "concurrency": 2,
            }
        }))
        config = load_executor_config(config_path=str(config_file))
        assert config["type"] == "command"
        assert config["concurrency"] == 2

    def test_load_config_with_overrides(self, tmp_path):
        config_file = tmp_path / "executor.json"
        config_file.write_text(json.dumps({
            "executor": {"type": "command", "command": ["echo"]}
        }))
        config = load_executor_config(
            config_path=str(config_file),
            cli_overrides={"concurrency": 4},
        )
        assert config["concurrency"] == 4

    def test_validate_valid_config(self):
        errors = validate_executor_config({
            "type": "command",
            "command": ["echo", "{task_path}"],
            "concurrency": 1,
        })
        assert errors == []

    def test_validate_unknown_template_var(self):
        errors = validate_executor_config({
            "type": "command",
            "command": ["echo", "{unknown_var}"],
        })
        assert any("Unknown template variable" in e for e in errors)

    def test_validate_unknown_type(self):
        errors = validate_executor_config({"type": "bogus"})
        assert any("Unknown executor type" in e for e in errors)

    def test_validate_invalid_concurrency(self):
        errors = validate_executor_config({
            "type": "command",
            "command": ["echo"],
            "concurrency": 0,
        })
        assert any("Concurrency" in e for e in errors)

    def test_create_executor_factory_command(self):
        executor = create_executor({
            "type": "command",
            "command": ["echo", "hello"],
        })
        assert isinstance(executor, CommandExecutor)

    def test_create_executor_factory_manual(self):
        executor = create_executor({"type": "manual"})
        assert isinstance(executor, ManualExecutor)


# ---------------------------------------------------------------------------
# execute_workers integration tests
# ---------------------------------------------------------------------------

class TestExecuteWorkers:
    def test_launches_pending_only(self, tmp_path):
        manifest = _make_manifest(3)
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        # Mark chunk-0001 as done with a result
        P.worker_result_path(run_dir, "chunk-0001").write_text("# Done\n")
        update_chunk_state(status, "chunk-0001", "done")
        save_status(status, run_dir)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
            output_mode="file",
        )

        status = load_status(run_dir)
        result = execute_workers(manifest, status, run_dir, executor)

        assert result["launched"] == 2  # chunk-0002 and chunk-0003
        assert result["succeeded"] == 2

    def test_skips_done_chunks(self, tmp_path):
        manifest = _make_manifest(2)
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        # Mark both done
        for cid in ["chunk-0001", "chunk-0002"]:
            P.worker_result_path(run_dir, cid).write_text("# Done\n")
            update_chunk_state(status, cid, "done")
        save_status(status, run_dir)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        result = execute_workers(manifest, status, run_dir, executor)
        assert result["launched"] == 0

    def test_skips_failed_by_default(self, tmp_path):
        manifest = _make_manifest(2)
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "failed")
        save_status(status, run_dir)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        result = execute_workers(manifest, status, run_dir, executor)
        # Only chunk-0002 (pending) should launch
        assert result["launched"] == 1

    def test_retry_failed(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        update_chunk_state(status, "chunk-0001", "failed")
        save_status(status, run_dir)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        result = execute_workers(
            manifest, status, run_dir, executor,
            retry_failed=True,
        )
        assert result["launched"] == 1
        assert result["succeeded"] == 1

    def test_only_filter(self, tmp_path):
        manifest = _make_manifest(3)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        result = execute_workers(
            manifest, status, run_dir, executor,
            only=["chunk-0002"],
        )
        assert result["launched"] == 1
        assert "chunk-0002" in result["chunks"]

    def test_records_attempts(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        execute_workers(manifest, status, run_dir, executor)

        status = load_status(run_dir)
        entry = status["chunks"]["chunk-0001"]
        assert entry["state"] == "done"
        assert len(entry["attempts"]) == 1
        assert entry["attempts"][0]["state"] == "done"

    def test_validates_result(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        # Script that writes empty file
        script = tmp_path / "empty-worker.sh"
        script.write_text('#!/bin/bash\ntouch "$1"\n', encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        result = execute_workers(manifest, status, run_dir, executor)

        assert result["failed"] == 1
        status = load_status(run_dir)
        assert status["chunks"]["chunk-0001"]["state"] == "failed"

    def test_materializes_tasks_when_missing(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        assert not P.tasks_index_path(run_dir).exists()

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        execute_workers(manifest, status, run_dir, executor)

        # Tasks should have been auto-materialized
        assert P.tasks_index_path(run_dir).exists()

    def test_failed_execution_records_error(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_failing_script(tmp_path)
        executor = CommandExecutor(command=[str(script)])

        status = load_status(run_dir)
        result = execute_workers(manifest, status, run_dir, executor)

        assert result["failed"] == 1
        status = load_status(run_dir)
        entry = status["chunks"]["chunk-0001"]
        assert entry["state"] == "failed"
        assert "last_error" in entry


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCLIOrchestrateDryRun:
    def test_dry_run_unchanged(self, tmp_path, source_file):
        """V2 dry-run behavior is preserved."""
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])
        main(["orchestrate", str(run_dir)])  # default is dry-run, should not fail


class TestCLIExecute:
    def test_execute_with_command_executor(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        script = _make_fake_worker_script(tmp_path)

        config = {
            "executor": {
                "type": "command",
                "command": [str(script), "{result_path}"],
                "output_mode": "file",
            }
        }
        config_path = tmp_path / "exec.json"
        config_path.write_text(json.dumps(config))

        try:
            main(["execute", str(run_dir), "--executor-config", str(config_path)])
        except SystemExit:
            pass

        # All chunks should have results
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        status = load_status(run_dir)
        for c in manifest["chunks"]:
            assert status["chunks"][c["id"]]["state"] == "done"

    def test_execute_json_output(self, tmp_path, source_file, capsys):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        script = _make_fake_worker_script(tmp_path)
        config = {
            "executor": {
                "type": "command",
                "command": [str(script), "{result_path}"],
            }
        }
        config_path = tmp_path / "exec.json"
        config_path.write_text(json.dumps(config))
        capsys.readouterr()

        try:
            main(["execute", str(run_dir), "--executor-config", str(config_path), "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "launched" in result
        assert "succeeded" in result

    def test_orchestrate_execute_alias(self, tmp_path, source_file):
        """orchestrate --execute should work same as execute."""
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        script = _make_fake_worker_script(tmp_path)
        config = {
            "executor": {
                "type": "command",
                "command": [str(script), "{result_path}"],
            }
        }
        config_path = tmp_path / "exec.json"
        config_path.write_text(json.dumps(config))

        try:
            main(["orchestrate", str(run_dir), "--execute",
                  "--executor-config", str(config_path)])
        except SystemExit:
            pass

        status = load_status(run_dir)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        for c in manifest["chunks"]:
            assert status["chunks"][c["id"]]["state"] == "done"


# ---------------------------------------------------------------------------
# Event logging, attempt logs, and orchestration.json integration tests
# ---------------------------------------------------------------------------

class TestExecutionEventLogging:
    """Verify that execute_workers emits lifecycle events to events.jsonl."""

    def test_events_emitted_on_success(self, tmp_path):
        manifest = _make_manifest(2)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        execute_workers(manifest, status, run_dir, executor)

        from gutenberg.reporting import read_events
        events = read_events(run_dir)
        # Should have start + done events for each chunk
        started = [e for e in events if e["event"] == "worker_started"]
        done = [e for e in events if e["event"] == "worker_done"]
        assert len(started) == 2
        assert len(done) == 2
        # Check ordering: started before done for each chunk
        assert events[0]["event"] == "worker_started"
        assert events[1]["event"] == "worker_done"

    def test_events_emitted_on_failure(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_failing_script(tmp_path)
        executor = CommandExecutor(command=[str(script)])

        status = load_status(run_dir)
        execute_workers(manifest, status, run_dir, executor)

        from gutenberg.reporting import read_events
        events = read_events(run_dir)
        started = [e for e in events if e["event"] == "worker_started"]
        failed = [e for e in events if e["event"] == "worker_failed"]
        assert len(started) == 1
        assert len(failed) == 1
        assert failed[0]["chunk_id"] == "chunk-0001"
        assert "error" in failed[0]


class TestAttemptLogFiles:
    """Verify that per-attempt log files are written under logs/workers/."""

    def test_log_files_written_on_success(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        execute_workers(manifest, status, run_dir, executor)

        log_file = P.worker_log_path(run_dir, "chunk-0001", 1)
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "Worker attempt 1 for chunk-0001" in content
        assert "Success: True" in content

    def test_log_files_written_on_failure(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_failing_script(tmp_path)
        executor = CommandExecutor(command=[str(script)])

        status = load_status(run_dir)
        execute_workers(manifest, status, run_dir, executor)

        log_file = P.worker_log_path(run_dir, "chunk-0001", 1)
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "Success: False" in content
        assert "Error:" in content

    def test_attempt_log_path_recorded_in_status(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        execute_workers(manifest, status, run_dir, executor)

        status = load_status(run_dir)
        entry = status["chunks"]["chunk-0001"]
        assert len(entry["attempts"]) == 1
        assert entry["attempts"][0].get("log_path") is not None
        assert "logs/workers/" in entry["attempts"][0]["log_path"]


class TestOrchestrationJsonWritten:
    """Verify orchestration.json is written after execute_workers."""

    def test_orchestration_json_created(self, tmp_path):
        manifest = _make_manifest(2)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        execute_workers(manifest, status, run_dir, executor)

        orch_path = P.orchestration_json_path(run_dir)
        assert orch_path.exists()
        data = json.loads(orch_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "1.0"
        assert data["workers"]["done"] == 2

    def test_orchestration_json_after_partial(self, tmp_path):
        manifest = _make_manifest(2)
        run_dir = _setup_run(tmp_path, manifest)

        # Make chunk-0001 fail and chunk-0002 succeed
        fail_script = _make_failing_script(tmp_path)
        success_script = _make_fake_worker_script(tmp_path)

        # First run only chunk-0001 with failing script
        executor_fail = CommandExecutor(command=[str(fail_script)])
        status = load_status(run_dir)
        execute_workers(
            manifest, status, run_dir, executor_fail,
            only=["chunk-0001"],
        )

        # Then run chunk-0002 with success
        executor_ok = CommandExecutor(
            command=[str(success_script), "{result_path}"],
        )
        status = load_status(run_dir)
        execute_workers(
            manifest, status, run_dir, executor_ok,
            only=["chunk-0002"],
        )

        orch_path = P.orchestration_json_path(run_dir)
        assert orch_path.exists()
        data = json.loads(orch_path.read_text(encoding="utf-8"))
        assert data["workers"]["done"] == 1
        assert data["workers"]["failed"] == 1


class TestMaxAttemptsRespected:
    def test_retry_failed_respects_max_attempts(self, tmp_path):
        """Spec 12: chunk at max_attempts not retried automatically."""
        manifest = _make_manifest(1)
        manifest["executor"] = {"max_attempts": 2}
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        # Simulate 2 prior failed attempts (at max)
        cid = "chunk-0001"
        update_chunk_state(status, cid, "failed")
        status["chunks"][cid]["attempts"] = [
            {"attempt": 1, "state": "failed"},
            {"attempt": 2, "state": "failed"},
        ]
        save_status(status, run_dir)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
            output_mode="file",
        )

        status = load_status(run_dir)
        result = execute_workers(
            manifest, status, run_dir, executor,
            retry_failed=True,
        )
        # Should not have launched anything
        assert result["launched"] == 0
        assert result["succeeded"] == 0

    def test_retry_failed_launches_below_max(self, tmp_path):
        """Failed chunk below max_attempts is retried with --retry-failed."""
        manifest = _make_manifest(1)
        manifest["executor"] = {"max_attempts": 3}
        run_dir = _setup_run(tmp_path, manifest)
        status = load_status(run_dir)

        cid = "chunk-0001"
        update_chunk_state(status, cid, "failed")
        status["chunks"][cid]["attempts"] = [
            {"attempt": 1, "state": "failed"},
        ]
        save_status(status, run_dir)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
            output_mode="file",
        )

        status = load_status(run_dir)
        result = execute_workers(
            manifest, status, run_dir, executor,
            retry_failed=True,
        )
        assert result["launched"] == 1
        assert result["succeeded"] == 1


class TestLogMaxBytesOverride:
    """Spec 15: --log-max-bytes CLI flag overrides per-attempt log cap."""

    def test_log_max_bytes_caps_log_size(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        execute_workers(
            manifest, status, run_dir, executor,
            log_max_bytes=10,
        )

        log_file = P.worker_log_path(run_dir, "chunk-0001", 1)
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "[TRUNCATED]" in content

    def test_log_max_bytes_none_uses_default(self, tmp_path):
        manifest = _make_manifest(1)
        run_dir = _setup_run(tmp_path, manifest)

        script = _make_fake_worker_script(tmp_path)
        executor = CommandExecutor(
            command=[str(script), "{result_path}"],
        )

        status = load_status(run_dir)
        execute_workers(
            manifest, status, run_dir, executor,
            log_max_bytes=None,
        )

        log_file = P.worker_log_path(run_dir, "chunk-0001", 1)
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "[TRUNCATED]" not in content
