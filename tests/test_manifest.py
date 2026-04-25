"""Tests for manifest generation and validation."""

import json
from datetime import datetime, timezone

from gutenberg.chunking import chunk_text
from gutenberg.manifest import build_manifest, write_manifest, validate_manifest
from gutenberg import paths as P


def _make_run(tmp_path, text="Hello world.\n\nSecond paragraph.\n", **kwargs):
    """Helper to create a full run directory for testing."""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()
    P.chunks_dir(run_dir).mkdir()
    P.prompts_dir(run_dir).mkdir()
    P.results_dir(run_dir).mkdir()

    # Write source
    P.source_path(run_dir).write_text(text, encoding="utf-8")

    chunks = chunk_text(text, **kwargs)

    # Write chunk files
    for chunk in chunks:
        P.chunk_path(run_dir, chunk.id).write_text(
            f"---\nchunk_id: {chunk.id}\n---\n\n{chunk.text}", encoding="utf-8"
        )

    manifest = build_manifest(
        input_path="/tmp/source.txt",
        source_text=text,
        chunks=chunks,
        chunk_size=kwargs.get("chunk_size", 50_000),
        overlap=kwargs.get("overlap", 2_000),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    # Write prompt files
    for name in (P.ORCHESTRATOR_PROMPT, P.WORKER_PROMPT, P.SYNTHESIS_PROMPT):
        (P.prompts_dir(run_dir) / name).write_text("prompt\n", encoding="utf-8")

    # Write .gitkeep
    (P.results_dir(run_dir) / ".gitkeep").touch()

    return run_dir, manifest, chunks


class TestBuildManifest:
    def test_required_fields(self, tmp_path):
        _, manifest, _ = _make_run(tmp_path)
        for field in ("schema_version", "tool", "created_at", "source", "settings", "prompts", "chunks", "results"):
            assert field in manifest

    def test_schema_version(self, tmp_path):
        _, manifest, _ = _make_run(tmp_path)
        assert manifest["schema_version"] == "1.0"

    def test_tool_info(self, tmp_path):
        _, manifest, _ = _make_run(tmp_path)
        assert manifest["tool"]["name"] == "gutenberg"
        assert manifest["tool"]["version"] == "0.1.0"

    def test_source_sha256(self, tmp_path):
        text = "Hello world.\n"
        _, manifest, _ = _make_run(tmp_path, text=text)
        import hashlib
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert manifest["source"]["sha256"] == expected

    def test_source_char_count(self, tmp_path):
        text = "Hello world.\n"
        _, manifest, _ = _make_run(tmp_path, text=text)
        assert manifest["source"]["char_count"] == len(text)

    def test_settings_match_args(self, tmp_path):
        _, manifest, _ = _make_run(tmp_path, chunk_size=1000, overlap=100)
        assert manifest["settings"]["chunk_size"] == 1000
        assert manifest["settings"]["overlap"] == 100
        assert manifest["settings"]["splitter"] == "boundary-aware-v1"

    def test_chunk_entries(self, tmp_path):
        text = "a" * 200
        _, manifest, chunks = _make_run(tmp_path, text=text, chunk_size=100, overlap=10)
        assert len(manifest["chunks"]) == len(chunks)
        for mc, c in zip(manifest["chunks"], chunks):
            assert mc["id"] == c.id
            assert mc["char_start"] == c.char_start
            assert mc["char_end"] == c.char_end
            assert mc["estimated_tokens"] == c.estimated_tokens

    def test_paths_are_relative(self, tmp_path):
        _, manifest, _ = _make_run(tmp_path)
        assert manifest["source"]["stored_path"] == "source.txt"
        assert manifest["prompts"]["orchestrator"].startswith("prompts/")
        for chunk in manifest["chunks"]:
            assert chunk["path"].startswith("chunks/")

    def test_results_pattern(self, tmp_path):
        _, manifest, _ = _make_run(tmp_path)
        assert "{chunk_id}" in manifest["results"]["expected_worker_pattern"]


class TestWriteManifest:
    def test_writes_valid_json(self, tmp_path):
        run_dir, manifest, _ = _make_run(tmp_path)
        path = write_manifest(manifest, run_dir)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["schema_version"] == "1.0"


class TestValidateManifest:
    def test_valid_manifest(self, tmp_path):
        run_dir, manifest, _ = _make_run(tmp_path)
        write_manifest(manifest, run_dir)
        errors = validate_manifest(manifest, run_dir)
        assert errors == []

    def test_missing_field(self, tmp_path):
        run_dir, manifest, _ = _make_run(tmp_path)
        del manifest["schema_version"]
        errors = validate_manifest(manifest, run_dir)
        assert any("schema_version" in e for e in errors)

    def test_missing_source_file(self, tmp_path):
        run_dir, manifest, _ = _make_run(tmp_path)
        P.source_path(run_dir).unlink()
        errors = validate_manifest(manifest, run_dir)
        assert any("source" in e.lower() for e in errors)

    def test_missing_chunk_file(self, tmp_path):
        text = "a" * 200
        run_dir, manifest, chunks = _make_run(tmp_path, text=text, chunk_size=100, overlap=10)
        # Delete first chunk file
        P.chunk_path(run_dir, chunks[0].id).unlink()
        errors = validate_manifest(manifest, run_dir)
        assert any("chunk" in e.lower() for e in errors)

    def test_missing_prompt_file(self, tmp_path):
        run_dir, manifest, _ = _make_run(tmp_path)
        P.orchestrator_prompt_path(run_dir).unlink()
        errors = validate_manifest(manifest, run_dir)
        assert any("prompt" in e.lower() or "orchestrator" in e.lower() for e in errors)
