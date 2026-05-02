"""Tests for run validation (spec 08)."""

import hashlib
import json

import pytest

from gutenberg.cli import main
from gutenberg.validation import validate_run
from gutenberg.status import create_status, save_status, load_status, update_chunk_state
from gutenberg import paths as P


def _ingest(tmp_path, text=None, chunk_size=500, overlap=50):
    """Helper: ingest a source file and return the run directory."""
    if text is None:
        paragraphs = []
        for i in range(20):
            paragraphs.append(
                f"## Section {i + 1}\n\n"
                f"This is paragraph {i + 1} of the test document. "
                f"It contains meaningful content for testing validation. "
                f"Each section has a heading for boundary detection.\n"
            )
        text = "\n".join(paragraphs)

    source = tmp_path / "source.txt"
    source.write_text(text, encoding="utf-8")
    run_dir = tmp_path / "run"
    main(["ingest", str(source), "--out", str(run_dir),
          "--chunk-size", str(chunk_size), "--overlap", str(overlap)])
    return run_dir


class TestValidateHappyPath:
    def test_valid_v2_run_passes(self, tmp_path):
        """A freshly ingested V2 run passes all checks."""
        run_dir = _ingest(tmp_path)
        checks = validate_run(run_dir, strict=True)
        assert all(c["passed"] for c in checks), [c for c in checks if not c["passed"]]

    def test_valid_v1_run_passes(self, tmp_path):
        """A V1-style run (no status.json, no per-chunk sha256) passes."""
        run_dir = _ingest(tmp_path)
        # Remove status.json and strip sha256 from manifest to simulate V1
        P.status_path(run_dir).unlink()
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        for chunk in manifest["chunks"]:
            chunk.pop("sha256", None)
        with open(P.manifest_path(run_dir), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        checks = validate_run(run_dir, strict=True)
        assert all(c["passed"] for c in checks), [c for c in checks if not c["passed"]]


class TestValidateManifest:
    def test_missing_manifest(self, tmp_path):
        """Missing manifest.json → early clear failure."""
        run_dir = tmp_path / "empty-run"
        run_dir.mkdir()
        checks = validate_run(run_dir)
        assert len(checks) == 1
        assert not checks[0]["passed"]
        assert "manifest" in checks[0]["detail"].lower()

    def test_invalid_json_manifest(self, tmp_path):
        """Corrupt manifest.json (invalid JSON) → early failure."""
        run_dir = _ingest(tmp_path)
        P.manifest_path(run_dir).write_text("{invalid json", encoding="utf-8")
        checks = validate_run(run_dir)
        assert any(not c["passed"] and "json" in c["check"].lower() for c in checks)


class TestValidateChunkFiles:
    def test_missing_chunk_file(self, tmp_path):
        """Deleting a chunk file → failure identifying the file."""
        run_dir = _ingest(tmp_path)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        first_chunk = manifest["chunks"][0]
        (run_dir / first_chunk["path"]).unlink()
        checks = validate_run(run_dir)
        failed = [c for c in checks if not c["passed"]]
        assert any(first_chunk["id"] in c["detail"] for c in failed)

    def test_corrupted_chunk_strict(self, tmp_path):
        """Corrupting a chunk file → hash check fails in strict mode."""
        run_dir = _ingest(tmp_path)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        first_chunk = manifest["chunks"][0]
        chunk_path = run_dir / first_chunk["path"]
        chunk_path.write_text("CORRUPTED CONTENT", encoding="utf-8")
        checks = validate_run(run_dir, strict=True)
        hash_checks = [c for c in checks if "hash" in c["check"].lower()]
        assert any(not c["passed"] for c in hash_checks)

    def test_corrupted_chunk_quick(self, tmp_path):
        """Corrupting a chunk file → hash check skipped in quick mode (passes)."""
        run_dir = _ingest(tmp_path)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        first_chunk = manifest["chunks"][0]
        chunk_path = run_dir / first_chunk["path"]
        chunk_path.write_text("CORRUPTED CONTENT", encoding="utf-8")
        checks = validate_run(run_dir, strict=False)
        # In quick mode, no hash checks should fail
        hash_fails = [c for c in checks if "hash" in c["check"].lower() and not c["passed"]]
        assert len(hash_fails) == 0

    def test_v1_manifest_no_sha256_skips_gracefully(self, tmp_path):
        """V1 manifest without per-chunk sha256 → hash check skipped."""
        run_dir = _ingest(tmp_path)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        for chunk in manifest["chunks"]:
            chunk.pop("sha256", None)
        with open(P.manifest_path(run_dir), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        checks = validate_run(run_dir, strict=True)
        # No hash failures since no hashes to check
        hash_fails = [c for c in checks if "hash" in c["check"].lower() and not c["passed"]]
        assert len(hash_fails) == 0


class TestValidatePromptFiles:
    def test_missing_prompt_file(self, tmp_path):
        """Missing prompt file → failure."""
        run_dir = _ingest(tmp_path)
        P.worker_prompt_path(run_dir).unlink()
        checks = validate_run(run_dir)
        failed = [c for c in checks if not c["passed"]]
        assert any("prompt" in c["check"].lower() or "worker" in c["detail"].lower() for c in failed)


class TestValidateStatusConsistency:
    def test_status_done_but_result_missing(self, tmp_path):
        """status.json says done but result file missing → inconsistency."""
        run_dir = _ingest(tmp_path)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        status = create_status(manifest)
        first_cid = manifest["chunks"][0]["id"]
        update_chunk_state(status, first_cid, "done")
        save_status(status, run_dir)
        # Do NOT create the result file
        checks = validate_run(run_dir)
        failed = [c for c in checks if not c["passed"]]
        assert any("status" in c["check"].lower() and first_cid in c["detail"] for c in failed)

    def test_valid_run_with_status(self, tmp_path):
        """V2 run with consistent status.json passes."""
        run_dir = _ingest(tmp_path)
        checks = validate_run(run_dir)
        status_checks = [c for c in checks if "status" in c["check"].lower()]
        assert all(c["passed"] for c in status_checks)


class TestValidateResultFiles:
    def test_empty_result_file_flagged(self, tmp_path):
        """Empty result file → flagged."""
        run_dir = _ingest(tmp_path)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        first_cid = manifest["chunks"][0]["id"]
        result_file = P.worker_result_path(run_dir, first_cid)
        result_file.write_text("", encoding="utf-8")
        checks = validate_run(run_dir)
        failed = [c for c in checks if not c["passed"]]
        assert any("empty" in c["detail"].lower() for c in failed)

    def test_results_directory_missing(self, tmp_path):
        """Results directory missing → failure."""
        run_dir = _ingest(tmp_path)
        import shutil
        shutil.rmtree(P.results_dir(run_dir))
        checks = validate_run(run_dir)
        failed = [c for c in checks if not c["passed"]]
        assert any("results" in c["check"].lower() or "results" in c["detail"].lower() for c in failed)

    def test_source_file_missing(self, tmp_path):
        """Source file missing → failure."""
        run_dir = _ingest(tmp_path)
        P.source_path(run_dir).unlink()
        checks = validate_run(run_dir)
        failed = [c for c in checks if not c["passed"]]
        assert any("source" in c["check"].lower() for c in failed)


class TestValidateCLI:
    def test_json_output_valid(self, tmp_path, capsys):
        """--json output is valid JSON with per-check results."""
        run_dir = _ingest(tmp_path)
        capsys.readouterr()  # discard ingest output
        main(["validate", str(run_dir), "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert all("check" in c and "passed" in c and "detail" in c for c in data)

    def test_exit_code_0_all_pass(self, tmp_path):
        """Exit code 0 when all checks pass."""
        run_dir = _ingest(tmp_path)
        # Should not raise SystemExit
        main(["validate", str(run_dir)])

    def test_exit_code_1_on_failure(self, tmp_path):
        """Exit code 1 when any check fails."""
        run_dir = _ingest(tmp_path)
        P.worker_prompt_path(run_dir).unlink()
        with pytest.raises(SystemExit) as exc_info:
            main(["validate", str(run_dir)])
        assert exc_info.value.code == 1

    def test_missing_run_dir(self, tmp_path):
        """Non-existent run dir → error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["validate", str(tmp_path / "nonexistent")])
        assert exc_info.value.code == 1

    def test_human_readable_output(self, tmp_path, capsys):
        """Human-readable output shows pass/fail marks."""
        run_dir = _ingest(tmp_path)
        main(["validate", str(run_dir)])
        captured = capsys.readouterr()
        assert "\u2713" in captured.out  # checkmark
        assert "passed" in captured.out

    def test_quick_mode(self, tmp_path):
        """--quick skips hash verification."""
        run_dir = _ingest(tmp_path)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        first_chunk = manifest["chunks"][0]
        chunk_path = run_dir / first_chunk["path"]
        chunk_path.write_text("CORRUPTED", encoding="utf-8")
        # Quick mode should still pass (no hash check)
        main(["validate", str(run_dir), "--quick"])


class TestManifestSHA256:
    def test_ingest_adds_sha256_to_manifest(self, tmp_path):
        """Ingestion adds per-chunk sha256 to manifest."""
        run_dir = _ingest(tmp_path)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        for chunk in manifest["chunks"]:
            assert "sha256" in chunk
            assert len(chunk["sha256"]) == 64  # hex SHA-256

    def test_sha256_matches_file_content(self, tmp_path):
        """Per-chunk sha256 matches actual file content on disk."""
        run_dir = _ingest(tmp_path)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        for chunk in manifest["chunks"]:
            file_path = run_dir / chunk["path"]
            actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            assert chunk["sha256"] == actual_hash


# ---------------------------------------------------------------------------
# Attempt log path validation (V3)
# ---------------------------------------------------------------------------

class TestValidateAttemptLogs:
    def test_valid_attempt_logs(self, tmp_path, source_file, capsys):
        """Attempt logs that exist should pass validation."""
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        from gutenberg.executor import CommandExecutor, execute_workers
        import stat

        # Create fake worker script
        script = tmp_path / "worker.sh"
        content = "# Chunk Summary\nDone.\n"
        staging = tmp_path / "_content.md"
        staging.write_text(content)
        script.write_text(f'#!/bin/bash\ncp "{staging}" "$1"\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        executor = CommandExecutor(command=[str(script), "{result_path}"])
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        status = load_status(run_dir)
        execute_workers(manifest, status, run_dir, executor)
        capsys.readouterr()

        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        checks = json.loads(captured.out)
        log_check = next((c for c in checks if c["check"] == "attempt_logs_exist"), None)
        assert log_check is not None
        assert log_check["passed"]

    def test_dangling_attempt_log_path(self, tmp_path, source_file, capsys):
        """Missing attempt log files should fail validation."""
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        # Manually add a status entry with a bogus log_path
        status = load_status(run_dir)
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        cid = manifest["chunks"][0]["id"]
        status["chunks"][cid]["attempts"] = [{
            "attempt": 1,
            "state": "done",
            "log_path": "logs/workers/nonexistent.log",
        }]
        save_status(status, run_dir)
        capsys.readouterr()

        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        checks = json.loads(captured.out)
        log_check = next((c for c in checks if c["check"] == "attempt_logs_exist"), None)
        assert log_check is not None
        assert not log_check["passed"]
        assert "nonexistent.log" in log_check["detail"]


# ---------------------------------------------------------------------------
# Worker result section checks (V3)
# ---------------------------------------------------------------------------

class TestValidateWorkerSections:
    def test_section_warnings_reported(self, tmp_path, source_file, capsys):
        """Worker results missing sections should be reported as warnings."""
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        # Write a result file that's valid but missing required sections
        cid = manifest["chunks"][0]["id"]
        P.worker_result_path(run_dir, cid).write_text(
            "# Some analysis\n\nThis is an analysis without required sections.\n"
        )
        capsys.readouterr()

        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        checks = json.loads(captured.out)
        section_check = next((c for c in checks if c["check"] == "worker_result_sections"), None)
        assert section_check is not None
        assert section_check["passed"]  # warning-level, still passes
        assert "missing" in section_check["detail"].lower()


class TestValidateUnknownChunks:
    def test_unknown_chunks_reported(self, tmp_path, capsys):
        """Validation detects chunks in status.json not present in manifest."""
        run_dir = _ingest(tmp_path)
        status = load_status(run_dir)
        # Add a fake chunk to status
        status["chunks"]["chunk-9999"] = {
            "state": "pending",
            "transitions": [{"state": "pending", "timestamp": "2026-01-01T00:00:00+00:00"}],
        }
        save_status(status, run_dir)

        capsys.readouterr()
        try:
            main(["validate", str(run_dir), "--json"])
        except SystemExit:
            pass

        captured = capsys.readouterr()
        checks = json.loads(captured.out)
        unknown_check = next((c for c in checks if c["check"] == "status_unknown_chunks"), None)
        assert unknown_check is not None
        assert unknown_check["passed"]  # warning-level
        assert "chunk-9999" in unknown_check["detail"]
