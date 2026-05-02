# Implementation Plan — Gutenberg V3

> **Status:** V1 complete. V2 complete. **V3 complete.** All 5 specs (11-15) implemented.
> **Last updated:** 2026-05-01
> **Current baseline:** 348 tests passing (confirmed 2026-05-01).
> **Latest validation commits:** `128a71a` (spec 15 reporting). Tag: `0.7.0`.
> **Schema posture:** Keep manifest schema additive where possible. Preserve V1/V2 run compatibility.

## Completion Record

### V1

- Specs 01–06 satisfied.
- Ingestion, chunking, manifest, prompts, and manual orchestration built.
- Dogfood on Frankenstein validated the decompose → analyze snippets → synthesize pattern.

### V2

- Specs 07–10 satisfied.
- Built:
  - chunk context enrichment
  - `status.json`
  - `gutenberg status`
  - `gutenberg validate`
  - `gutenberg orchestrate`
  - dry-run orchestration planning
  - JSON orchestration plans
  - shell script generation
  - resume/skip completed chunks
  - synthesis readiness checks
- Test baseline: `python -m pytest -q` → `166 passed`.

## V2 Dogfood Validation (2026-04-24)

- Source: Frankenstein; or, the Modern Prometheus, Project Gutenberg #84
- Author: Mary Shelley
- Character count: 419,240
- Chunk count: 9 at default 50k/2k settings
- Verified: status, validation, context enrichment, orchestration dry-run, JSON plan output, script output, resume behavior, and synthesis readiness
- Failure modes verified: deleted chunk, edited chunk/hash mismatch, empty result file, missing `status.json`
- Bug found and fixed: stale `status.json` could disagree with filesystem after manual result writes
- Fix: `20eeea9 fix: reconcile status.json with filesystem on every read`
- Related fix: `bc86c69 fix: sentinel values for first/last chunk neighbor context`
- V2 orchestration baseline: `f2abb05 feat: automated orchestration — gutenberg orchestrate CLI + plan/script generation (spec 10)`
- Revised verdict: **V2 validated — ready for V3 specs**

### V2 Notes Carried Into V3

- The shared worker prompt containing literal `{chunk_number}` is not a V2 blocker because actual position metadata lives in each chunk file's frontmatter.
- ~~V3 should improve ergonomics by materializing per-chunk worker task files or task payloads with concrete chunk numbers, paths, and result targets.~~ → Done in Slice 1 (spec 14).
- V2 script output is an operational scaffold. V3 should replace scaffold/TODO status updates with real lifecycle-aware execution and auditable logs.

### V3 Slice 1 Complete (2026-05-01)

- **Spec 14 — Per-Chunk Task Materialization** fully implemented.
- New module: `src/gutenberg/tasks.py` — `generate_worker_task`, `generate_synthesis_task`, `build_task_index`, `materialize_tasks`, `check_staleness`.
- Extended `paths.py` with V3 path helpers (tasks, logs, reports, orchestration).
- New CLI subcommand: `gutenberg tasks <run-dir> [--refresh] [--dry-run] [--json]`.
- Extended `validation.py`: task index JSON check, task file existence, unresolved placeholder detection.
- 40 new tests. Total: 206 passing.
- Commit: `9121f71`.

### V3 Slice 2 Complete (2026-05-01)

- **Spec 12 — Worker Lifecycle, Retry, Failure, and Resume** fully implemented.
- New module: `src/gutenberg/lifecycle.py` — attempt management, result validation, stale-running reconciliation, mark/retry/skip operations.
- Extended `status.py`: `skipped` state, atomic writes via `os.replace`, enhanced `reconcile_status` (V3 states), `summarize_failures`.
- New CLI subcommands: `gutenberg mark`, `gutenberg retry`, `gutenberg skip`, `gutenberg status --failures`.
- 56 new tests. Total: 262 passing.
- Commit: `8dd6e65`.

### V3 Slice 3 Complete (2026-05-01)

- **Spec 11 — Executor / Worker Launch Integration** fully implemented.
- New module: `src/gutenberg/executor.py` — `CommandExecutor`, `ManualExecutor`, `execute_workers`, config management.
- Extended CLI: `gutenberg execute`, `gutenberg orchestrate --execute`, executor flags.
- Updated existing test: `--execute` now requires config instead of old "not implemented" error.
- 27 new tests. Total: 289 passing.
- Commit: `d4eb615`.

### V3 Slice 4 Complete (2026-05-01)

- **Spec 13 — Synthesis Execution** fully implemented.
- New module: `src/gutenberg/synthesis.py` — readiness checks, input building, full/partial execution.
- New CLI: `gutenberg synthesize` with `--execute`, `--partial`, `--force`, `--json`.
- Extended validation: synthesis status consistency check.
- 19 new tests. Total: 308 passing.
- Commit: `a89136a`.

### V3 Slice 5 Complete (2026-05-01)

- **Spec 15 — Run Artifacts, Logs, and Reporting** fully implemented.
- New module: `src/gutenberg/reporting.py` — event log (JSONL), orchestration summary, report building.
- New CLI: `gutenberg report` with `--json`, `--markdown`, `--write`, `--include-validation`.
- Extended validation: orchestration.json, event log, report JSON checks.
- 22 new tests. Total: 330 passing.
- Commit: `128a71a`.


### V3 Slice 6: Execution Wiring (2026-05-01)

- **Event logging integration**: `execute_workers` and `execute_synthesis` now emit lifecycle events to `logs/events.jsonl` via `append_event`. Events: `worker_started`, `worker_done`, `worker_failed`, `synthesis_started`, `synthesis_done`, `synthesis_failed`.
- **Per-attempt log files**: Each worker attempt writes a bounded (512KB) log file to `logs/workers/{chunk_id}.attempt-{NNN}.log`. Each synthesis attempt writes to `logs/synthesis/attempt-{NNN}.log`. Log paths are recorded in status attempt entries.
- **Orchestration summary**: `execute_workers` now writes `orchestration.json` after every execution via `write_orchestration_summary`, with executor config metadata.
- **Mark/retry/skip event logging**: `gutenberg mark`, `gutenberg retry`, and `gutenberg skip` CLI commands now emit lifecycle events to `logs/events.jsonl`.
- **Validation enhancements**: `gutenberg validate` now checks attempt log paths referenced in status.json and reports missing worker result sections as warnings.
- **18 new tests** covering event emission, log file creation, log path recording, orchestration.json generation, mark/retry/skip event logging, attempt log validation, and worker result section checking.
- **Test growth:** 330 → 348 tests.
### V3 Summary

- **All 5 V3 specs implemented** in recommended order (14 → 12 → 11 → 13 → 15).
- **New modules:** `tasks.py`, `lifecycle.py`, `executor.py`, `synthesis.py`, `reporting.py`.
- **Extended:** `paths.py`, `status.py`, `cli.py`, `validation.py`.
- **New CLI commands:** `tasks`, `mark`, `retry`, `skip`, `execute`, `synthesize`, `report`.
- **CLI flags:** `--failures`, `--execute`, `--partial`, `--force`, `--refresh`, `--concurrency`, `--timeout-seconds`, `--executor-config`, `--retry-failed`, `--only`, `--include-validation`.
- **Test growth:** 166 (V2) → 330 (V3) = +164 tests.
- **V1/V2 backward compatibility preserved** throughout.

