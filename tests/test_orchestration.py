"""Tests for orchestration planning and script generation."""

import json

from gutenberg.cli import main
from gutenberg.orchestration import (
    build_plan,
    format_plan_text,
    format_plan_json,
    generate_script,
    check_synthesis,
    format_worker_command,
)
from gutenberg.status import (
    create_status,
    save_status,
    load_status,
    update_chunk_state,
    infer_status,
)
from gutenberg.prompts import generate_orchestrator_prompt
from gutenberg import paths as P


def _ingest(tmp_path, source_file):
    """Helper: run ingest and return (run_dir, manifest, status)."""
    run_dir = tmp_path / "run"
    main(["ingest", str(source_file), "--out", str(run_dir),
          "--chunk-size", "500", "--overlap", "50"])
    manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
    status = load_status(run_dir)
    return run_dir, manifest, status


class TestBuildPlan:
    def test_fresh_run_all_pending(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        assert len(plan["pending"]) == len(manifest["chunks"])
        assert len(plan["done"]) == 0
        assert not plan["synthesis_ready"]

    def test_partial_run(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        # Mark first 3 chunks as done
        chunk_ids = [c["id"] for c in manifest["chunks"]]
        for cid in chunk_ids[:3]:
            update_chunk_state(status, cid, "done")
            # Create result file
            P.worker_result_path(run_dir, cid).write_text(f"Analysis for {cid}\n")
        save_status(status, run_dir)

        plan = build_plan(manifest, status)
        assert len(plan["done"]) == 3
        assert len(plan["pending"]) == len(chunk_ids) - 3

    def test_complete_run_synthesis_ready(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        for c in manifest["chunks"]:
            update_chunk_state(status, c["id"], "done")
            P.worker_result_path(run_dir, c["id"]).write_text(f"Analysis for {c['id']}\n")
        save_status(status, run_dir)

        plan = build_plan(manifest, status)
        assert plan["synthesis_ready"]
        assert len(plan["pending"]) == 0
        assert len(plan["blockers"]) == 0

    def test_skip_failed(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        chunk_ids = [c["id"] for c in manifest["chunks"]]
        # Mark all done except one failed
        for cid in chunk_ids[:-1]:
            update_chunk_state(status, cid, "done")
        update_chunk_state(status, chunk_ids[-1], "failed")
        save_status(status, run_dir)

        plan = build_plan(manifest, status, skip_failed=True)
        assert len(plan["skipped"]) == 1
        assert plan["skipped"][0]["id"] == chunk_ids[-1]

    def test_failed_retried_by_default(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        chunk_ids = [c["id"] for c in manifest["chunks"]]
        update_chunk_state(status, chunk_ids[0], "failed")
        save_status(status, run_dir)

        plan = build_plan(manifest, status)
        pending_ids = [c["id"] for c in plan["pending"]]
        assert chunk_ids[0] in pending_ids


class TestFormatPlanText:
    def test_plan_text_contains_run_name(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        text = format_plan_text(plan, run_dir)
        assert run_dir.name in text

    def test_plan_text_shows_pending_chunks(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        text = format_plan_text(plan, run_dir)
        assert "Pending" in text
        assert "chunk-0001" in text


class TestFormatPlanJSON:
    def test_json_is_valid(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        result = format_plan_json(plan, run_dir)
        # Should be JSON-serializable
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        assert "pending" in parsed
        assert "summary" in parsed

    def test_json_summary_counts(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        result = format_plan_json(plan, run_dir)
        assert result["summary"]["total"] == len(manifest["chunks"])
        assert result["summary"]["pending"] == len(manifest["chunks"])
        assert result["summary"]["done"] == 0


class TestGenerateScript:
    def test_script_has_shebang(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        script = generate_script(plan, run_dir)
        assert script.startswith("#!/usr/bin/env bash")

    def test_script_has_set_e(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        script = generate_script(plan, run_dir)
        assert "set -e" in script

    def test_script_one_command_per_pending(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        script = generate_script(plan, run_dir)
        for chunk in plan["pending"]:
            assert chunk["id"] in script

    def test_script_standalone_commands(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        script = generate_script(plan, run_dir)
        # Each worker section references the worker prompt
        assert "worker.md" in script


class TestCheckSynthesis:
    def test_synthesis_not_ready(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        plan = build_plan(manifest, status)
        result = check_synthesis(plan, manifest, run_dir)
        assert not result["ready"]
        assert len(result["blockers"]) > 0

    def test_synthesis_ready(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        for c in manifest["chunks"]:
            update_chunk_state(status, c["id"], "done")
        save_status(status, run_dir)

        plan = build_plan(manifest, status)
        result = check_synthesis(plan, manifest, run_dir)
        assert result["ready"]
        assert "synthesis_prompt" in result
        assert "command" in result


class TestWorkerCommand:
    def test_command_references_files(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        chunk = manifest["chunks"][0]
        cmd = format_worker_command(run_dir, chunk)
        assert chunk["id"] in cmd
        assert "worker.md" in cmd


class TestCLIOrchestrate:
    def test_dry_run_default(self, tmp_path, source_file, capsys):
        run_dir, _, _ = _ingest(tmp_path, source_file)
        rc = main(["orchestrate", str(run_dir)])
        captured = capsys.readouterr()
        assert "Orchestration Plan" in captured.out
        assert "Pending" in captured.out

    def test_json_output(self, tmp_path, source_file, capsys):
        run_dir, _, _ = _ingest(tmp_path, source_file)
        capsys.readouterr()  # clear ingest output
        main(["orchestrate", str(run_dir), "--json"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "pending" in result
        assert "summary" in result

    def test_synthesis_check_not_ready(self, tmp_path, source_file, capsys):
        run_dir, _, _ = _ingest(tmp_path, source_file)
        try:
            main(["orchestrate", str(run_dir), "--synthesis-check"])
            assert False, "Should have exited with code 1"
        except SystemExit as e:
            assert e.code == 1
        captured = capsys.readouterr()
        assert "NOT READY" in captured.out

    def test_synthesis_check_ready(self, tmp_path, source_file, capsys):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        for c in manifest["chunks"]:
            update_chunk_state(status, c["id"], "done")
            # Create result files so reconcile doesn't demote back to pending
            P.worker_result_path(run_dir, c["id"]).write_text("analysis\n", encoding="utf-8")
        save_status(status, run_dir)

        main(["orchestrate", str(run_dir), "--synthesis-check"])
        captured = capsys.readouterr()
        assert "READY" in captured.out

    def test_script_output(self, tmp_path, source_file, capsys):
        run_dir, _, _ = _ingest(tmp_path, source_file)
        main(["orchestrate", str(run_dir), "--script"])
        captured = capsys.readouterr()
        assert "#!/usr/bin/env bash" in captured.out
        assert "set -e" in captured.out

    def test_execute_not_implemented(self, tmp_path, source_file, capsys):
        run_dir, _, _ = _ingest(tmp_path, source_file)
        try:
            main(["orchestrate", str(run_dir), "--execute"])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1
        captured = capsys.readouterr()
        assert "not implemented" in captured.err.lower()

    def test_v1_run_without_status(self, tmp_path, source_file, capsys):
        run_dir, _, _ = _ingest(tmp_path, source_file)
        # Remove status.json to simulate V1 run
        P.status_path(run_dir).unlink()
        main(["orchestrate", str(run_dir)])
        captured = capsys.readouterr()
        assert "Orchestration Plan" in captured.out

    def test_skip_failed_flag(self, tmp_path, source_file, capsys):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        capsys.readouterr()  # clear ingest output
        chunk_ids = [c["id"] for c in manifest["chunks"]]
        # Mark all done except one failed
        for cid in chunk_ids[:-1]:
            update_chunk_state(status, cid, "done")
        update_chunk_state(status, chunk_ids[-1], "failed")
        save_status(status, run_dir)

        main(["orchestrate", str(run_dir), "--skip-failed", "--json"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["summary"]["skipped"] == 1

    def test_resume_idempotent(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        chunk_ids = [c["id"] for c in manifest["chunks"]]
        # Mark first 3 as done
        for cid in chunk_ids[:3]:
            update_chunk_state(status, cid, "done")
        save_status(status, run_dir)

        # Build plan twice — should be the same
        status1 = load_status(run_dir)
        plan1 = build_plan(manifest, status1)
        plan2 = build_plan(manifest, status1)
        assert [c["id"] for c in plan1["pending"]] == [c["id"] for c in plan2["pending"]]

    def test_dry_run_no_changes(self, tmp_path, source_file):
        run_dir, manifest, status = _ingest(tmp_path, source_file)
        # Snapshot files before
        status_before = P.status_path(run_dir).read_text(encoding="utf-8")
        manifest_before = P.manifest_path(run_dir).read_text(encoding="utf-8")

        main(["orchestrate", str(run_dir)])

        # Verify nothing changed
        assert P.status_path(run_dir).read_text(encoding="utf-8") == status_before
        assert P.manifest_path(run_dir).read_text(encoding="utf-8") == manifest_before

    def test_empty_run_graceful(self, tmp_path):
        """An ingested run with zero chunks handles gracefully."""
        run_dir = tmp_path / "empty_run"
        run_dir.mkdir()
        P.chunks_dir(run_dir).mkdir()
        P.prompts_dir(run_dir).mkdir()
        P.results_dir(run_dir).mkdir()
        manifest = {
            "schema_version": "1.0",
            "tool": {"name": "gutenberg", "version": "0.2.0"},
            "created_at": "2026-01-01T00:00:00+00:00",
            "source": {"input_path": "test.txt", "stored_path": "source.txt",
                        "title": "", "author": "", "sha256": "abc", "char_count": 0},
            "settings": {"chunk_size": 50000, "overlap": 2000, "context_chars": 200,
                          "splitter": "boundary-aware-v1", "estimated_token_method": "chars_div_4"},
            "prompts": {},
            "chunks": [],
            "results": {"directory": "results", "expected_worker_pattern": "results/{chunk_id}.analysis.md",
                         "expected_synthesis_path": "results/synthesis.md"},
        }
        P.manifest_path(run_dir).write_text(json.dumps(manifest), encoding="utf-8")
        status = create_status(manifest)
        save_status(status, run_dir)

        plan = build_plan(manifest, status)
        assert plan["synthesis_ready"]
        assert len(plan["pending"]) == 0


class TestOrchestratorPromptV2:
    def test_v2_cli_references(self):
        from gutenberg.chunking import chunk_text
        from gutenberg.manifest import build_manifest
        from datetime import datetime, timezone

        text = "Hello world.\n"
        chunks = chunk_text(text)
        manifest = build_manifest(
            input_path="/tmp/source.txt", source_text=text, chunks=chunks,
            chunk_size=50000, overlap=2000,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        prompt = generate_orchestrator_prompt(manifest, "test-run")
        assert "gutenberg status" in prompt
        assert "gutenberg validate" in prompt
        assert "gutenberg orchestrate" in prompt
        assert "--script" in prompt
        assert "--synthesis-check" in prompt

    def test_no_automation_claims_preserved(self):
        from gutenberg.chunking import chunk_text
        from gutenberg.manifest import build_manifest
        from datetime import datetime, timezone

        text = "Hello world.\n"
        chunks = chunk_text(text)
        manifest = build_manifest(
            input_path="/tmp/source.txt", source_text=text, chunks=chunks,
            chunk_size=50000, overlap=2000,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        prompt = generate_orchestrator_prompt(manifest, "test-run")
        assert "automated" not in prompt.lower() or "no automated" in prompt.lower()
