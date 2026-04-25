"""Run directory path helpers."""

from pathlib import Path

SOURCE_FILENAME = "source.txt"
MANIFEST_FILENAME = "manifest.json"
STATUS_FILENAME = "status.json"
CHUNKS_DIR = "chunks"
PROMPTS_DIR = "prompts"
RESULTS_DIR = "results"

ORCHESTRATOR_PROMPT = "orchestrator.md"
WORKER_PROMPT = "worker.md"
SYNTHESIS_PROMPT = "synthesis.md"


def source_path(run_dir: Path) -> Path:
    return run_dir / SOURCE_FILENAME


def manifest_path(run_dir: Path) -> Path:
    return run_dir / MANIFEST_FILENAME


def chunks_dir(run_dir: Path) -> Path:
    return run_dir / CHUNKS_DIR


def chunk_path(run_dir: Path, chunk_id: str) -> Path:
    return chunks_dir(run_dir) / f"{chunk_id}.md"


def prompts_dir(run_dir: Path) -> Path:
    return run_dir / PROMPTS_DIR


def orchestrator_prompt_path(run_dir: Path) -> Path:
    return prompts_dir(run_dir) / ORCHESTRATOR_PROMPT


def worker_prompt_path(run_dir: Path) -> Path:
    return prompts_dir(run_dir) / WORKER_PROMPT


def synthesis_prompt_path(run_dir: Path) -> Path:
    return prompts_dir(run_dir) / SYNTHESIS_PROMPT


def results_dir(run_dir: Path) -> Path:
    return run_dir / RESULTS_DIR


def worker_result_path(run_dir: Path, chunk_id: str) -> Path:
    return results_dir(run_dir) / f"{chunk_id}.analysis.md"


def synthesis_result_path(run_dir: Path) -> Path:
    return results_dir(run_dir) / "synthesis.md"


def status_path(run_dir: Path) -> Path:
    return run_dir / STATUS_FILENAME
