"""Tests for the CLI integration."""

import json

from gutenberg.cli import main
from gutenberg import paths as P


class TestCLIHappyPath:
    def test_basic_ingest(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])

        assert run_dir.exists()
        assert P.source_path(run_dir).exists()
        assert P.manifest_path(run_dir).exists()
        assert P.chunks_dir(run_dir).exists()
        assert P.prompts_dir(run_dir).exists()
        assert P.results_dir(run_dir).exists()
        assert (P.results_dir(run_dir) / ".gitkeep").exists()

    def test_manifest_is_valid_json(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        assert manifest["schema_version"] == "1.0"

    def test_chunks_exist(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])

        chunk_files = list(P.chunks_dir(run_dir).glob("chunk-*.md"))
        assert len(chunk_files) > 0

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        assert len(manifest["chunks"]) == len(chunk_files)

    def test_prompts_exist(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])

        assert P.orchestrator_prompt_path(run_dir).exists()
        assert P.worker_prompt_path(run_dir).exists()
        assert P.synthesis_prompt_path(run_dir).exists()

    def test_source_copied(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir)])

        original = source_file.read_text(encoding="utf-8")
        copied = P.source_path(run_dir).read_text(encoding="utf-8")
        assert original == copied


class TestCLICustomOptions:
    def test_custom_chunk_size(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "300", "--overlap", "30"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        assert manifest["settings"]["chunk_size"] == 300
        assert manifest["settings"]["overlap"] == 30

    def test_title_and_author(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--title", "My Book", "--author", "Test Author"])

        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        assert manifest["source"]["title"] == "My Book"
        assert manifest["source"]["author"] == "Test Author"


class TestCLIForce:
    def test_refuses_nonempty_dir(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "existing.txt").write_text("existing\n")

        try:
            main(["ingest", str(source_file), "--out", str(run_dir)])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1

    def test_force_overwrites(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "existing.txt").write_text("existing\n")

        main(["ingest", str(source_file), "--out", str(run_dir), "--force"])

        assert P.manifest_path(run_dir).exists()
        assert not (run_dir / "existing.txt").exists()


class TestCLIErrors:
    def test_missing_source(self, tmp_path):
        try:
            main(["ingest", str(tmp_path / "nonexistent.txt"), "--out", str(tmp_path / "run")])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1

    def test_invalid_chunk_size(self, tmp_path, source_file):
        try:
            main(["ingest", str(source_file), "--out", str(tmp_path / "run"),
                  "--chunk-size", "0"])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1

    def test_overlap_too_large(self, tmp_path, source_file):
        try:
            main(["ingest", str(source_file), "--out", str(tmp_path / "run"),
                  "--chunk-size", "100", "--overlap", "100"])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1

    def test_no_command(self):
        try:
            main([])
            assert False, "Should have exited"
        except SystemExit as e:
            assert e.code == 1


class TestCLIContextChars:
    def test_context_chars_option(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir), "--context-chars", "100"])
        manifest = json.loads(P.manifest_path(run_dir).read_text(encoding="utf-8"))
        assert manifest["settings"]["context_chars"] == 100

    def test_chunk_frontmatter_has_v2_fields(self, tmp_path, source_file):
        run_dir = tmp_path / "run"
        main(["ingest", str(source_file), "--out", str(run_dir),
              "--chunk-size", "500", "--overlap", "50"])
        chunk_files = sorted(P.chunks_dir(run_dir).glob("chunk-*.md"))
        assert len(chunk_files) > 0
        content = chunk_files[0].read_text(encoding="utf-8")
        assert "chunk_index:" in content
        assert "chunk_number:" in content
        assert "total_chunks:" in content
        assert "prev_context:" in content
        assert "next_context:" in content
