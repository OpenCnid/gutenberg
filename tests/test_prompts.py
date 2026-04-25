"""Tests for prompt generation."""

from datetime import datetime, timezone

from gutenberg.chunking import chunk_text
from gutenberg.manifest import build_manifest
from gutenberg.prompts import (
    generate_orchestrator_prompt,
    generate_worker_prompt,
    generate_synthesis_prompt,
    write_prompts,
)
from gutenberg import paths as P


def _make_manifest(text="Hello world.\n", chunk_size=50_000, overlap=2_000):
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    return build_manifest(
        input_path="/tmp/source.txt",
        source_text=text,
        chunks=chunks,
        chunk_size=chunk_size,
        overlap=overlap,
        title="Test Title",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class TestOrchestratorPrompt:
    def test_contains_chunk_list(self):
        manifest = _make_manifest()
        prompt = generate_orchestrator_prompt(manifest, "test-run")
        assert "chunk-0001" in prompt

    def test_manual_workflow(self):
        prompt = generate_orchestrator_prompt(_make_manifest(), "test-run")
        assert "manual" in prompt.lower()

    def test_no_automation_claims(self):
        prompt = generate_orchestrator_prompt(_make_manifest(), "test-run")
        assert "automated" not in prompt.lower() or "no automated" in prompt.lower()

    def test_references_run_paths(self):
        prompt = generate_orchestrator_prompt(_make_manifest(), "test-run")
        assert "manifest.json" in prompt
        assert "results/" in prompt


class TestWorkerPrompt:
    def test_required_sections(self):
        prompt = generate_worker_prompt(_make_manifest(), "test-run")
        for section in [
            "Chunk Summary",
            "Key Claims",
            "Important Quotes",
            "Entities",
            "Open Questions",
            "Connections",
            "Synthesis Notes",
        ]:
            assert section in prompt

    def test_result_path_pattern(self):
        prompt = generate_worker_prompt(_make_manifest(), "test-run")
        assert "analysis.md" in prompt


class TestSynthesisPrompt:
    def test_references_results(self):
        prompt = generate_synthesis_prompt(_make_manifest(), "test-run")
        assert "analysis.md" in prompt

    def test_mentions_missing_chunks(self):
        prompt = generate_synthesis_prompt(_make_manifest(), "test-run")
        assert "missing" in prompt.lower()


class TestWritePrompts:
    def test_writes_all_files(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        P.prompts_dir(run_dir).mkdir()

        manifest = _make_manifest()
        write_prompts(manifest, run_dir)

        assert P.orchestrator_prompt_path(run_dir).exists()
        assert P.worker_prompt_path(run_dir).exists()
        assert P.synthesis_prompt_path(run_dir).exists()

    def test_prompts_are_nonempty(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        P.prompts_dir(run_dir).mkdir()

        write_prompts(_make_manifest(), run_dir)

        for path in (
            P.orchestrator_prompt_path(run_dir),
            P.worker_prompt_path(run_dir),
            P.synthesis_prompt_path(run_dir),
        ):
            assert path.stat().st_size > 0
