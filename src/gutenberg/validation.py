"""Run validation — structural integrity and completeness checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from gutenberg import paths as P
from gutenberg.manifest import validate_manifest
from gutenberg.lifecycle import check_sections
from gutenberg.status import load_status

_SYNTHESIS_DONE_STATES = ("done", "partial")


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "passed": passed, "detail": detail}


def validate_run(run_dir: Path, strict: bool = True) -> list[dict[str, Any]]:
    """Validate structural integrity and completeness of a run directory.

    Returns a list of check results, each with ``check``, ``passed``, and
    ``detail`` keys.  The function is **read-only** — it never modifies the
    run directory.
    """
    results: list[dict[str, Any]] = []

    # 1. manifest.json exists and is valid JSON with required fields
    manifest_file = P.manifest_path(run_dir)
    if not manifest_file.exists():
        results.append(_check("manifest_exists", False, f"manifest.json not found in {run_dir}"))
        return results  # Can't continue without manifest

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as exc:
        results.append(_check("manifest_valid_json", False, f"manifest.json is not valid JSON: {exc}"))
        return results

    schema_errors = validate_manifest(manifest, run_dir)
    if schema_errors:
        results.append(_check("manifest_schema", False, "; ".join(schema_errors)))
    else:
        results.append(_check("manifest_schema", True, "manifest.json schema valid"))

    # 2. Source file exists
    source_stored = manifest.get("source", {}).get("stored_path", "")
    if source_stored:
        source_on_disk = run_dir / source_stored
        if source_on_disk.exists():
            results.append(_check("source_file", True, f"{source_stored} exists"))
        else:
            results.append(_check("source_file", False, f"Source file not found: {source_stored}"))

    # 3. Every chunk file exists + 4. SHA-256 hash check (strict only)
    chunks = manifest.get("chunks", [])
    all_chunks_present = True
    all_hashes_match = True
    for chunk in chunks:
        cid = chunk.get("id", "?")
        cpath = chunk.get("path", "")
        chunk_on_disk = run_dir / cpath
        if not chunk_on_disk.exists():
            results.append(_check("chunk_file_exists", False, f"Chunk file not found: {cpath} ({cid})"))
            all_chunks_present = False
            continue

        if strict:
            expected_hash = chunk.get("sha256")
            if expected_hash is not None:
                actual_hash = _sha256_file(chunk_on_disk)
                if actual_hash != expected_hash:
                    results.append(_check(
                        "chunk_hash",
                        False,
                        f"Hash mismatch for {cpath} ({cid}): expected {expected_hash[:16]}…, got {actual_hash[:16]}…",
                    ))
                    all_hashes_match = False
            # If manifest lacks sha256 (V1), skip gracefully — no failure

    if all_chunks_present:
        results.append(_check("chunk_files_exist", True, f"All {len(chunks)} chunk files present"))
    if strict and all_hashes_match and all_chunks_present:
        has_any_hash = any(c.get("sha256") for c in chunks)
        if has_any_hash:
            results.append(_check("chunk_hashes", True, "All chunk hashes verified"))

    # 5. Prompt files exist
    prompts_ok = True
    for role in ("orchestrator", "worker", "synthesis"):
        ppath = manifest.get("prompts", {}).get(role, "")
        if ppath and not (run_dir / ppath).exists():
            results.append(_check("prompt_file", False, f"Prompt file not found: {ppath}"))
            prompts_ok = False
    if prompts_ok:
        results.append(_check("prompt_files", True, "All prompt files present"))

    # 6. status.json consistency (if present)
    status = load_status(run_dir)
    if status is not None:
        status_ok = True
        for cid, entry in status.get("chunks", {}).items():
            state = entry.get("state", "")
            if state == "done":
                result_file = P.worker_result_path(run_dir, cid)
                if not result_file.exists() or result_file.stat().st_size == 0:
                    results.append(_check(
                        "status_consistency",
                        False,
                        f"status.json says {cid} is done but result file is missing or empty",
                    ))
                    status_ok = False
        if status_ok:
            results.append(_check("status_consistency", True, "status.json consistent with filesystem"))

        # 6b. Unknown chunks in status (not in manifest)
        manifest_ids = {c.get("id") for c in chunks}
        unknown = sorted(set(status.get("chunks", {}).keys()) - manifest_ids)
        if unknown:
            results.append(_check(
                "status_unknown_chunks",
                True,  # warning-level: pass but report
                f"Status contains chunks not in manifest: {', '.join(unknown[:10])}",
            ))

    # 7. Results directory exists
    rdir = manifest.get("results", {}).get("directory", "")
    if rdir:
        if (run_dir / rdir).exists():
            results.append(_check("results_directory", True, f"{rdir}/ exists"))
        else:
            results.append(_check("results_directory", False, f"Results directory not found: {rdir}"))

    # 8. Non-empty result files
    results_path = run_dir / rdir if rdir else None
    if results_path and results_path.exists():
        for result_file in sorted(results_path.glob("*.analysis.md")):
            if result_file.stat().st_size == 0:
                results.append(_check(
                    "result_file_nonempty",
                    False,
                    f"Result file is empty: {result_file.name}",
                ))

    # 9. Task index validation (V3, only when tasks/ exists)
    tasks_index = P.tasks_index_path(run_dir)
    if tasks_index.exists():
        try:
            index_data = json.loads(tasks_index.read_text(encoding="utf-8"))
            results.append(_check("task_index_valid_json", True, "tasks/index.json is valid JSON"))

            # Check each referenced task file exists
            workers = index_data.get("tasks", {}).get("workers", [])
            all_task_files_ok = True
            for w in workers:
                tp = w.get("task_path", "")
                if tp and not (run_dir / tp).exists():
                    results.append(_check(
                        "task_file_exists",
                        False,
                        f"Task file referenced by index not found: {tp}",
                    ))
                    all_task_files_ok = False

            synth_tp = index_data.get("tasks", {}).get("synthesis", {}).get("task_path", "")
            if synth_tp and not (run_dir / synth_tp).exists():
                results.append(_check(
                    "task_file_exists",
                    False,
                    f"Synthesis task file referenced by index not found: {synth_tp}",
                ))
                all_task_files_ok = False

            if all_task_files_ok:
                results.append(_check("task_files_exist", True, "All task files referenced by index exist"))

        except (json.JSONDecodeError, ValueError) as exc:
            results.append(_check("task_index_valid_json", False, f"tasks/index.json is not valid JSON: {exc}"))

        # 10. Check for unresolved placeholders in task files
        _PLACEHOLDERS = ("{chunk_id}", "{chunk_number}", "{total_chunks}", "{chunk_path}", "{result_path}")
        tasks_workers = P.tasks_workers_dir(run_dir)
        if tasks_workers.exists():
            placeholder_problems: list[str] = []
            for tf in sorted(tasks_workers.glob("*.worker.md")):
                content = tf.read_text(encoding="utf-8")
                for ph in _PLACEHOLDERS:
                    if ph in content:
                        placeholder_problems.append(f"{tf.name} contains {ph}")
            if placeholder_problems:
                results.append(_check(
                    "task_no_placeholders",
                    False,
                    "Unresolved placeholders: " + "; ".join(placeholder_problems),
                ))
            else:
                results.append(_check("task_no_placeholders", True, "No unresolved placeholders in task files"))

    # 11. orchestration.json validation (V3)
    orch_path = P.orchestration_json_path(run_dir)
    if orch_path.exists():
        try:
            orch_data = json.loads(orch_path.read_text(encoding="utf-8"))
            results.append(_check("orchestration_json_valid", True, "orchestration.json is valid JSON"))

            # Check events.jsonl reference
            events_ref = orch_data.get("artifacts", {}).get("events", "")
            if events_ref:
                events_file = run_dir / events_ref
                if events_file.exists():
                    results.append(_check("events_log_exists", True, "Event log file exists"))
                else:
                    results.append(_check("events_log_exists", False, f"Event log referenced but not found: {events_ref}"))
        except (json.JSONDecodeError, ValueError) as exc:
            results.append(_check("orchestration_json_valid", False, f"orchestration.json is not valid JSON: {exc}"))

    # 12. Report validation (V3)
    report_json = P.report_json_path(run_dir)
    if report_json.exists():
        try:
            json.loads(report_json.read_text(encoding="utf-8"))
            results.append(_check("report_json_valid", True, "reports/run-report.json is valid JSON"))
        except (json.JSONDecodeError, ValueError) as exc:
            results.append(_check("report_json_valid", False, f"reports/run-report.json is not valid JSON: {exc}"))

    # 13. Synthesis status consistency (V3)
    if status is not None:
        synth = status.get("synthesis", {})
        synth_state = synth.get("state")
        if synth_state in _SYNTHESIS_DONE_STATES:
            synth_result = P.synthesis_result_path(run_dir)
            if synth_result.exists() and synth_result.stat().st_size > 0:
                results.append(_check(
                    "synthesis_consistency",
                    True,
                    f"Synthesis status '{synth_state}' consistent with output file",
                ))
            else:
                results.append(_check(
                    "synthesis_consistency",
                    False,
                    f"Synthesis status is '{synth_state}' but output file is missing or empty",
                ))

    # 14. Attempt log path validation (V3)
    if status is not None:
        dangling_logs: list[str] = []
        for cid, entry in status.get("chunks", {}).items():
            for att in entry.get("attempts", []):
                lp = att.get("log_path")
                if lp and not (run_dir / lp).exists():
                    dangling_logs.append(f"{cid}: {lp}")
        # Also check synthesis attempts
        for att in status.get("synthesis", {}).get("attempts", []):
            lp = att.get("log_path")
            if lp and not (run_dir / lp).exists():
                dangling_logs.append(f"synthesis: {lp}")
        if dangling_logs:
            results.append(_check(
                "attempt_logs_exist",
                False,
                f"Dangling attempt log paths: {'; '.join(dangling_logs[:10])}",
            ))
        elif any(
            att.get("log_path")
            for entry in status.get("chunks", {}).values()
            for att in entry.get("attempts", [])
        ):
            results.append(_check("attempt_logs_exist", True, "All referenced attempt logs exist"))

    # 15. Worker result section checks (V3, warning-level)
    if rdir:
        sections_results_path = run_dir / rdir
        if sections_results_path.exists():
            missing_sections_report: list[str] = []
            for result_file in sorted(sections_results_path.glob("*.analysis.md")):
                if result_file.stat().st_size > 0:
                    try:
                        file_content = result_file.read_text(encoding="utf-8")
                        missing = check_sections(file_content)
                        if missing:
                            missing_sections_report.append(
                                f"{result_file.name}: missing {len(missing)} section(s)"
                            )
                    except (OSError, UnicodeDecodeError):
                        pass
            if missing_sections_report:
                results.append(_check(
                    "worker_result_sections",
                    True,  # warning-level — pass but report
                    f"Section warnings: {'; '.join(missing_sections_report[:10])}",
                ))

    return results
