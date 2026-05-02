"""Run artifacts, logs, and reporting — Spec 15.

Provides event logging, orchestration summaries, and run reports.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gutenberg import paths as P
from gutenberg.status import load_status, summarize_status, summarize_failures


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

def append_event(run_dir: Path, event: dict[str, Any]) -> None:
    """Append one JSON-line event to ``logs/events.jsonl``."""
    if "timestamp" not in event:
        event["timestamp"] = datetime.now(timezone.utc).isoformat()

    log_dir = P.logs_dir(run_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    events_path = log_dir / "events.jsonl"

    with open(events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def read_events(run_dir: Path) -> list[dict[str, Any]]:
    """Read all events from ``logs/events.jsonl``."""
    events_path = P.logs_dir(run_dir) / "events.jsonl"
    if not events_path.exists():
        return []
    events: list[dict[str, Any]] = []
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


# ---------------------------------------------------------------------------
# Orchestration summary
# ---------------------------------------------------------------------------

def build_orchestration_summary(
    manifest: dict[str, Any],
    status: dict[str, Any],
    run_dir: Path,
    executor_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble ``orchestration.json`` content."""
    summary = summarize_status(status)
    synth = status.get("synthesis", {})

    # Safe executor metadata (no secrets)
    executor_meta: dict[str, Any] = {}
    if executor_config:
        executor_meta["type"] = executor_config.get("type", "unknown")
        if "model" in executor_config:
            executor_meta["model"] = executor_config["model"]
        executor_meta["concurrency"] = executor_config.get("concurrency", 1)

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "run_dir": ".",
        "created_by": "gutenberg",
    }

    if executor_meta:
        result["executor"] = executor_meta

    result["workers"] = {
        "total": summary.get("total", 0),
        "done": summary.get("done", 0),
        "failed": summary.get("failed", 0),
        "missing": summary.get("missing", 0),
        "skipped": summary.get("skipped", 0),
        "pending": summary.get("pending", 0),
    }

    result["synthesis"] = {
        "state": synth.get("state", "not_started"),
        "result_path": str(P.RESULTS_DIR + "/synthesis.md"),
        "partial": synth.get("partial", False),
    }

    # Artifact paths
    artifacts: dict[str, str] = {}
    events_path = P.logs_dir(run_dir) / "events.jsonl"
    if events_path.exists():
        artifacts["events"] = "logs/events.jsonl"
    report_md = P.report_md_path(run_dir)
    if report_md.exists():
        artifacts["report_markdown"] = "reports/run-report.md"
    report_json = P.report_json_path(run_dir)
    if report_json.exists():
        artifacts["report_json"] = "reports/run-report.json"
    if artifacts:
        result["artifacts"] = artifacts

    return result


def write_orchestration_summary(
    manifest: dict[str, Any],
    status: dict[str, Any],
    run_dir: Path,
    executor_config: dict[str, Any] | None = None,
) -> Path:
    """Write ``orchestration.json`` to run directory."""
    summary = build_orchestration_summary(manifest, status, run_dir, executor_config)
    path = P.orchestration_json_path(run_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    return path


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------

def build_report(
    manifest: dict[str, Any],
    status: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    """Assemble report data from manifest, status, and filesystem."""
    source = manifest.get("source", {})
    settings = manifest.get("settings", {})
    chunks = manifest.get("chunks", [])
    summary = summarize_status(status)
    failures = summarize_failures(status)
    synth = status.get("synthesis", {})

    # Attempt/retry summary
    total_attempts = 0
    retried_chunks = 0
    for cid, entry in status.get("chunks", {}).items():
        attempts = entry.get("attempts", [])
        total_attempts += len(attempts)
        if len(attempts) > 1:
            retried_chunks += 1

    report: dict[str, Any] = {
        "source": {
            "title": source.get("title", ""),
            "author": source.get("author", ""),
            "char_count": source.get("char_count", 0),
        },
        "chunks": {
            "total": len(chunks),
            "done": summary.get("done", 0),
            "failed": summary.get("failed", 0),
            "missing": summary.get("missing", 0),
            "skipped": summary.get("skipped", 0),
            "pending": summary.get("pending", 0),
            "running": summary.get("running", 0),
        },
        "run_state": summary.get("run_state", "unknown"),
        "attempts": {
            "total_attempts": total_attempts,
            "retried_chunks": retried_chunks,
        },
        "failures": failures,
        "synthesis": {
            "state": synth.get("state", "not_started"),
            "partial": synth.get("partial", False),
            "result_path": str(P.RESULTS_DIR + "/synthesis.md"),
        },
        "settings": {
            "chunk_size": settings.get("chunk_size", 0),
            "overlap": settings.get("overlap", 0),
        },
        "artifacts": {
            "manifest": P.MANIFEST_FILENAME,
            "status": P.STATUS_FILENAME,
        },
    }

    # Add orchestration info if present
    orch_path = P.orchestration_json_path(run_dir)
    if orch_path.exists():
        try:
            orch = json.loads(orch_path.read_text(encoding="utf-8"))
            report["executor"] = orch.get("executor", {})
            report["artifacts"]["orchestration"] = P.ORCHESTRATION_JSON
        except (json.JSONDecodeError, OSError):
            pass

    return report


def format_report_markdown(report: dict[str, Any]) -> str:
    """Render report dict as structured markdown."""
    lines: list[str] = []

    src = report.get("source", {})
    title = src.get("title", "Untitled")
    author = src.get("author", "")

    lines.append(f"# Run Report — {title}")
    lines.append("")

    lines.append("## Source")
    lines.append("")
    lines.append(f"- **Title:** {title}")
    if author:
        lines.append(f"- **Author:** {author}")
    lines.append(f"- **Characters:** {src.get('char_count', 'unknown'):,}")
    lines.append("")

    ch = report.get("chunks", {})
    lines.append("## Chunks")
    lines.append("")
    lines.append(f"- **Total:** {ch.get('total', 0)}")
    lines.append(f"- **Done:** {ch.get('done', 0)}")
    if ch.get("failed"):
        lines.append(f"- **Failed:** {ch['failed']}")
    if ch.get("missing"):
        lines.append(f"- **Missing:** {ch['missing']}")
    if ch.get("skipped"):
        lines.append(f"- **Skipped:** {ch['skipped']}")
    if ch.get("pending"):
        lines.append(f"- **Pending:** {ch['pending']}")
    lines.append("")

    lines.append(f"**Run state:** {report.get('run_state', 'unknown')}")
    lines.append("")

    att = report.get("attempts", {})
    if att.get("total_attempts"):
        lines.append("## Attempts")
        lines.append("")
        lines.append(f"- **Total attempts:** {att['total_attempts']}")
        if att.get("retried_chunks"):
            lines.append(f"- **Retried chunks:** {att['retried_chunks']}")
        lines.append("")

    failures = report.get("failures", [])
    if failures:
        lines.append("## Failures")
        lines.append("")
        for f in failures:
            line = f"- **{f['chunk_id']}**: {f['state']}"
            if "reason" in f:
                line += f" — {f['reason']}"
            elif "last_error" in f:
                le = f["last_error"]
                line += f" — {le.get('message', le.get('code', ''))}"
            lines.append(line)
        lines.append("")

    synth = report.get("synthesis", {})
    lines.append("## Synthesis")
    lines.append("")
    lines.append(f"- **State:** {synth.get('state', 'not_started')}")
    if synth.get("partial"):
        lines.append("- **Partial:** yes")
    lines.append(f"- **Output:** `{synth.get('result_path', '')}`")
    lines.append("")

    executor = report.get("executor", {})
    if executor:
        lines.append("## Executor")
        lines.append("")
        lines.append(f"- **Type:** {executor.get('type', 'unknown')}")
        if "model" in executor:
            lines.append(f"- **Model:** {executor['model']}")
        lines.append(f"- **Concurrency:** {executor.get('concurrency', 1)}")
        lines.append("")

    settings = report.get("settings", {})
    if settings:
        lines.append("## Settings")
        lines.append("")
        lines.append(f"- **Chunk size:** {settings.get('chunk_size', 0):,}")
        lines.append(f"- **Overlap:** {settings.get('overlap', 0):,}")
        lines.append("")

    return "\n".join(lines)


def format_report_json(report: dict[str, Any]) -> dict[str, Any]:
    """Return the report dict (already JSON-serializable)."""
    return report


def write_reports(
    report: dict[str, Any],
    run_dir: Path,
) -> tuple[Path, Path]:
    """Write ``reports/run-report.md`` and ``reports/run-report.json``."""
    reports = P.reports_dir(run_dir)
    reports.mkdir(parents=True, exist_ok=True)

    md_path = P.report_md_path(run_dir)
    md_path.write_text(format_report_markdown(report), encoding="utf-8")

    json_path = P.report_json_path(run_dir)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    return md_path, json_path
