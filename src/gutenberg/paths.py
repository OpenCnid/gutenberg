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

# V3 paths
TASKS_DIR = "tasks"
TASKS_WORKERS_DIR = "tasks/workers"
TASKS_INDEX = "tasks/index.json"
TASKS_SYNTHESIS = "tasks/synthesis.md"
LOGS_DIR = "logs"
LOGS_WORKERS_DIR = "logs/workers"
LOGS_SYNTHESIS_DIR = "logs/synthesis"
REPORTS_DIR = "reports"
ORCHESTRATION_JSON = "orchestration.json"


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


# V3 path helpers

def tasks_dir(run_dir: Path) -> Path:
    return run_dir / TASKS_DIR


def tasks_workers_dir(run_dir: Path) -> Path:
    return run_dir / TASKS_WORKERS_DIR


def tasks_index_path(run_dir: Path) -> Path:
    return run_dir / TASKS_INDEX


def worker_task_path(run_dir: Path, chunk_id: str) -> Path:
    return tasks_workers_dir(run_dir) / f"{chunk_id}.worker.md"


def synthesis_task_path(run_dir: Path) -> Path:
    return run_dir / TASKS_SYNTHESIS


def logs_dir(run_dir: Path) -> Path:
    return run_dir / LOGS_DIR


def logs_workers_dir(run_dir: Path) -> Path:
    return run_dir / LOGS_WORKERS_DIR


def logs_synthesis_dir(run_dir: Path) -> Path:
    return run_dir / LOGS_SYNTHESIS_DIR


def worker_log_path(run_dir: Path, chunk_id: str, attempt: int) -> Path:
    return logs_workers_dir(run_dir) / f"{chunk_id}.attempt-{attempt:03d}.log"


def synthesis_log_path(run_dir: Path, attempt: int) -> Path:
    return logs_synthesis_dir(run_dir) / f"attempt-{attempt:03d}.log"


def reports_dir(run_dir: Path) -> Path:
    return run_dir / REPORTS_DIR


def report_md_path(run_dir: Path) -> Path:
    return reports_dir(run_dir) / "run-report.md"


def report_json_path(run_dir: Path) -> Path:
    return reports_dir(run_dir) / "run-report.json"


def orchestration_json_path(run_dir: Path) -> Path:
    return run_dir / ORCHESTRATION_JSON
