# Implementation Plan — Gutenberg V3

> **Status:** V1 complete. V2 complete. V3 Slices 1-3 complete. Slice 4 (Spec 13) next.
> **Last updated:** 2026-05-01
> **Current baseline:** 289 tests passing (confirmed 2026-05-01).
> **Latest validation commits:** `d4eb615` (spec 11 executor).
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

## V3 Goal

Move from orchestration planning to **safe executable recursive orchestration** while keeping Gutenberg's artifact-first design.

Core question:

> How does Gutenberg safely run the worker/synthesis loop instead of only generating instructions?

V3 must preserve:

- Python stdlib-first approach unless a dependency is strongly justified
- JSON for machines
- markdown for agents and humans
- V1/V2 compatibility
- additive manifest/status evolution where possible
- dry-run/manual/script fallback pathways
- deterministic artifact layout
- explicit execution only; no hidden external agent calls
- tests for every new behavior

V3 must not:

- build a database or UI
- replace the simple file-based contract
- remove manual fallback
- silently run external agents without explicit `--execute`
- treat empty/malformed outputs as success

## Planned V3 Specs

| Spec | Topic | Purpose |
|------|-------|---------|
| 11 | Executor / Worker Launch Integration | Define explicit worker execution, executor config, bounded concurrency, and no-duplicate launch behavior. |
| 12 | Worker Lifecycle, Retry, Failure, and Resume | Define durable worker states, attempts, failure reasons, retry/skip/mark CLI support, and interruption recovery. |
| 13 | Synthesis Execution | Define actual synthesis execution, partial synthesis semantics, synthesis status, and output validation. |
| 14 | Per-Chunk Task Materialization | Generate deterministic concrete task files so workers do not see ambiguous placeholders. |
| 15 | Run Artifacts, Logs, and Reporting | Make executed runs auditable with logs, orchestration events, sanitized metadata, and final reports. |

## Recommended V3 Implementation Order

1. **Spec 14 — Per-Chunk Task Materialization**
2. **Spec 12 — Worker Lifecycle, Retry, Failure, and Resume**
3. **Spec 11 — Executor / Worker Launch Integration**
4. **Spec 13 — Synthesis Execution**
5. **Spec 15 — Run Artifacts, Logs, and Reporting**

---

## V3 Detailed Implementation Plan

### Architecture Overview

V3 adds five new modules and extends three existing ones. The dependency graph:

```
paths.py (extended) ← tasks.py (NEW, spec 14)
                    ← lifecycle.py (NEW, spec 12)
                    ← executor.py (NEW, spec 11)
                    ← synthesis.py (NEW, spec 13)
                    ← reporting.py (NEW, spec 15)

status.py (extended) ← lifecycle.py
cli.py (extended) ← all new modules
validation.py (extended) ← tasks, lifecycle, reporting artifacts
```

No external dependencies. All modules are stdlib-only Python.

### Cross-Cutting Decisions

1. **Atomic status writes.** Every status mutation writes to a `.tmp` file then `os.replace()` to the real path. This is already hinted in spec 12; standardize it in `save_status()`.
2. **V2 lazy upgrade.** V2 `status.json` files lacking V3 fields (attempts, task_path, synthesis) are valid and upgraded lazily on read — never eagerly rewritten by `load_status`.
3. **`skipped` state.** Added to `CHUNK_STATES`. `compute_run_state` updated: `{done, skipped}` → `partial`; `skipped` included in partial semantics.
4. **Deterministic JSON.** All new JSON artifacts use `json.dump(..., indent=2, sort_keys=True)` for stable output.
5. **Path conventions.** `paths.py` gains constants/helpers for `tasks/`, `logs/`, `reports/`, `orchestration.json`. All paths are relative POSIX-style in artifacts, absolute `Path` objects in Python code.
6. **Test strategy.** Each slice gets its own test file (e.g., `test_tasks.py`, `test_lifecycle.py`). Shared fixtures in `conftest.py` for creating populated run directories with manifest/status/chunks.

---

### Slice 1: Spec 14 — Per-Chunk Task Materialization

**New file:** `src/gutenberg/tasks.py`
**Extended:** `paths.py`, `cli.py`, `manifest.py` (additive fields), `validation.py`
**New tests:** `tests/test_tasks.py`

#### 1a. `paths.py` extensions

Add constants and helpers:

```python
TASKS_DIR = "tasks"
TASKS_WORKERS_DIR = "tasks/workers"
TASKS_INDEX = "tasks/index.json"
TASKS_SYNTHESIS = "tasks/synthesis.md"
LOGS_DIR = "logs"
LOGS_WORKERS_DIR = "logs/workers"
LOGS_SYNTHESIS_DIR = "logs/synthesis"
REPORTS_DIR = "reports"
ORCHESTRATION_JSON = "orchestration.json"

def tasks_dir(run_dir): ...
def tasks_workers_dir(run_dir): ...
def tasks_index_path(run_dir): ...
def worker_task_path(run_dir, chunk_id): ...  # tasks/workers/{chunk_id}.worker.md
def synthesis_task_path(run_dir): ...          # tasks/synthesis.md
def logs_dir(run_dir): ...
def logs_workers_dir(run_dir): ...
def logs_synthesis_dir(run_dir): ...
def worker_log_path(run_dir, chunk_id, attempt): ...  # logs/workers/{chunk_id}.attempt-{NNN}.log
def synthesis_log_path(run_dir, attempt): ...
def reports_dir(run_dir): ...
def report_md_path(run_dir): ...
def report_json_path(run_dir): ...
def orchestration_json_path(run_dir): ...
```

#### 1b. `tasks.py` module

Core functions:

- `generate_worker_task(manifest, chunk, run_dir_name) -> str` — renders a concrete worker task markdown for one chunk. Uses manifest metadata + chunk frontmatter values. No `{chunk_number}` placeholders. Includes: title, author, run dir, manifest path, chunk id, chunk number, total chunks, chunk path, result path, prev/next context, inferred section, required output format, analysis instructions.
- `generate_synthesis_task(manifest, status, run_dir_name, partial=False) -> str` — renders the synthesis task. Lists all expected worker results in manifest order, marks each as available/missing/failed/skipped based on current status. Includes partial-synthesis gap section when `partial=True`.
- `build_task_index(manifest) -> dict` — builds `tasks/index.json` content.
- `materialize_tasks(manifest, status, run_dir, refresh=False) -> dict` — orchestrates task generation. Writes `tasks/workers/*.worker.md`, `tasks/synthesis.md`, `tasks/index.json`. Returns summary dict. When `refresh=False`, skips files whose content would be identical (compare before write). When `refresh=True`, always writes.
- `check_staleness(manifest, run_dir) -> list[dict]` — checks each expected task file against current manifest; returns list of stale/missing entries.

Design notes:

- Worker tasks pull data from `manifest["chunks"]` — they do not re-read chunk files. The manifest already has chunk_id, chunk_number, total_chunks, char_start, char_end, prev_context, next_context, inferred_section.
- The shared `prompts/worker.md` template is *not* used as a Jinja/format template. Instead, `generate_worker_task` constructs the task from scratch using the same structural format but with all values baked in. This avoids format-string injection and keeps tasks deterministic.
- No timestamps in generated task files (determinism).

#### 1c. CLI additions

New subcommand: `gutenberg tasks <run-dir> [--refresh] [--dry-run] [--json]`

- `--dry-run`: print summary of what would be written, no file changes.
- `--refresh`: regenerate stale/all tasks.
- `--json`: machine-readable output.
- Default (no flags): materialize missing tasks, skip up-to-date ones.

#### 1d. Manifest additive fields

After task materialization, optionally update manifest with:

```json
{
  "tasks": {
    "directory": "tasks",
    "index": "tasks/index.json",
    "worker_pattern": "tasks/workers/{chunk_id}.worker.md",
    "synthesis": "tasks/synthesis.md"
  }
}
```

And per-chunk `"task_path"` field. Manifest writes use the existing `write_manifest` with sort_keys for stability.

Decision: manifest update is *opt-in* — `materialize_tasks` returns metadata, caller decides whether to write manifest. This avoids unexpected manifest mutations during dry-run.

#### 1e. Validation extensions

`validate_run` gains:

- Check `tasks/index.json` is valid JSON if present.
- Check that each task file referenced by `tasks/index.json` exists.
- Check that task files contain no unresolved `{chunk_id}` / `{chunk_number}` / `{total_chunks}` / `{chunk_path}` / `{result_path}` placeholders.

#### 1f. Tests (~25–30 tests)

- `test_generate_worker_task_concrete_values` — no placeholders in output.
- `test_generate_worker_task_all_metadata` — chunk id/number/total/path/result_path/context present.
- `test_generate_synthesis_task_full` — lists all results as available.
- `test_generate_synthesis_task_partial` — marks gaps correctly.
- `test_build_task_index_schema` — valid JSON, relative POSIX paths, correct chunk count.
- `test_materialize_creates_files` — all expected files on disk.
- `test_materialize_idempotent` — second run with no changes writes nothing.
- `test_materialize_refresh` — `refresh=True` rewrites even identical files.
- `test_materialize_dry_run` — no file system changes.
- `test_staleness_detection` — detects missing/outdated tasks.
- `test_cli_tasks_default` — integration test of `gutenberg tasks <run>`.
- `test_cli_tasks_dry_run` — no file changes.
- `test_cli_tasks_json` — valid JSON output.
- `test_validation_task_index` — validate catches invalid task index.
- `test_validation_no_placeholders` — validate flags unresolved placeholders.
- `test_v2_run_without_tasks` — validation passes for V2 runs lacking task files.
- `test_determinism` — same manifest produces byte-identical tasks.

---

### Slice 2: Spec 12 — Worker Lifecycle, Retry, Failure, and Resume

**New file:** `src/gutenberg/lifecycle.py`
**Extended:** `status.py`, `cli.py`, `validation.py`
**New tests:** `tests/test_lifecycle.py`

#### 2a. `status.py` extensions

- Add `"skipped"` to `CHUNK_STATES`.
- Update `compute_run_state`:
  - `{done}` → `complete`
  - `{done, skipped}` → `partial`
  - `{done, failed}` or `{done, missing}` or `{done, failed, missing}` → `partial`
  - `{done, skipped, failed, missing}` subsets → `partial`
  - `{pending}` → `ingested`
  - everything else with work remaining → `in_progress`
- Update `reconcile_status` to handle V3 states:
  - `running` + valid result → `done`
  - `running` + no result + stale timeout exceeded → `failed` with reason `interrupted_or_stale`
  - `done` + empty/missing result → `missing`
  - `done` + result exists but fails content validation → `failed` with validation reason
- Enhance `save_status` to use atomic write (write `.tmp`, `os.replace`).
- Add `update_chunk_state_v3(status, chunk_id, new_state, **kwargs)` that accepts optional `reason`, `attempt_data`, `task_path`, etc. for V3-enriched transitions.

#### 2b. `lifecycle.py` module

Core functions:

- `create_attempt(chunk_id, executor_type, model=None) -> dict` — creates an attempt record with timestamp, attempt number, executor, model.
- `record_attempt_success(attempt, result_path, log_path=None) -> dict` — fills in end time, state=done, result path.
- `record_attempt_failure(attempt, error_code, error_message, exit_code=None, log_path=None) -> dict` — fills in failure metadata.
- `validate_worker_result(result_path) -> tuple[bool, str | None]` — checks file exists, non-empty, UTF-8, not whitespace-only, contains required sections. Returns `(valid, error_reason)`.
- `get_required_sections() -> list[str]` — returns the 7 required section headings from spec 05/12.
- `check_sections(content) -> list[str]` — returns list of missing section headings (warning-level initially, per spec 12 note).
- `resolve_stale_running(status, manifest, run_dir, timeout_seconds=1800) -> list[str]` — finds chunks marked `running` longer than timeout, reconciles to done/failed. Returns list of chunk IDs resolved.
- `mark_chunk(status, chunk_id, state, reason) -> None` — applies `gutenberg mark` logic with validation.
- `retry_chunks(status, manifest, which="failed", chunk_ids=None, force=False) -> list[str]` — resets eligible chunks to `pending`. Respects `max_attempts` unless `force=True`.
- `skip_chunk(status, chunk_id, reason) -> None` — marks chunk `skipped`.
- `get_max_attempts(manifest) -> int` — reads from manifest `executor.max_attempts` or default `3`.

Design notes:

- Attempt records live inside `status["chunks"][cid]["attempts"]` list. V2 status files without this key get `[]` on lazy read.
- `last_error` is a convenience copy of the latest failed attempt's error info, kept at the chunk level for quick access.
- Section validation is initially warning-only (per spec 12 allowance) but structured so flipping to error-level is a one-line change.

#### 2c. CLI additions

New subcommands:

- `gutenberg mark <run-dir> <chunk-id> <state> --reason "..."` — requires `--reason` for `failed` and `skipped`.
- `gutenberg retry <run-dir> --failed [--force]` — reset failed/missing chunks to pending.
- `gutenberg retry <run-dir> --chunk <chunk-id> [--force]` — reset specific chunk.
- `gutenberg skip <run-dir> <chunk-id> --reason "..."` — mark chunk skipped.
- Extend `gutenberg status <run-dir> --failures` — show only failed/skipped/missing chunks with reasons.

#### 2d. Reconciliation enhancements

Existing `reconcile_status` is enhanced to:
- Handle `skipped` state (preserve; don't promote to done just because a result exists unless explicitly re-tried).
- Handle stale `running` (delegate to `resolve_stale_running`).
- Handle result content validation (empty file → `failed`, not just `missing`).
- Preserve attempt history during reconciliation.

#### 2e. Validation extensions

- Check attempt count consistency.
- Warn if chunks have `max_attempts` reached and are still `failed`.
- Report stale `running` entries.

#### 2f. Tests (~30–35 tests)

- `test_skipped_state_in_run_state` — compute_run_state handles skipped.
- `test_create_attempt_fields` — correct structure.
- `test_record_success/failure` — fields populated.
- `test_validate_result_valid/empty/missing/whitespace/no_sections` — all validation paths.
- `test_resolve_stale_running_with_result` — promotes to done.
- `test_resolve_stale_running_without_result` — fails with reason.
- `test_mark_chunk_failed/skipped/pending` — state transitions.
- `test_mark_done_requires_result` — rejects done without file.
- `test_retry_failed_chunks` — resets to pending, preserves attempts.
- `test_retry_respects_max_attempts` — refuses without force.
- `test_retry_force_overrides_max` — allows with force.
- `test_skip_chunk_records_reason` — reason and timestamp.
- `test_reconcile_v3_states` — all reconciliation paths.
- `test_reconcile_preserves_attempts` — attempt history survives reconciliation.
- `test_atomic_status_write` — write + rename pattern.
- `test_v2_status_lazy_upgrade` — V2 files load cleanly, gain empty attempts.
- `test_cli_mark/retry/skip` — integration tests for each subcommand.
- `test_status_failures_flag` — `--failures` shows only problem chunks.
- `test_section_check` — required sections detected/missing.

---

### Slice 3: Spec 11 — Executor / Worker Launch Integration

**New file:** `src/gutenberg/executor.py`
**Extended:** `cli.py`, `orchestration.py`, `status.py`
**New tests:** `tests/test_executor.py`

#### 3a. `executor.py` module

Core types and functions:

```python
@dataclass
class ExecutorResult:
    success: bool
    exit_code: int | None = None
    error_message: str | None = None
    log_path: str | None = None

class Executor(Protocol):
    def launch(self, task_path: str, result_path: str, timeout: int) -> ExecutorResult: ...
```

Executor implementations:

- **`CommandExecutor`** — runs a configured command template via `subprocess.run`. Template variables: `{run_dir}`, `{chunk_id}`, `{chunk_path}`, `{task_path}`, `{result_path}`, `{worker_prompt_path}`. Two output modes: `file` (executor writes result directly) and `stdout` (Gutenberg captures stdout to result path). Timeout via `subprocess.run(timeout=...)`.
- **`ManualExecutor`** — no-op executor that prints instructions and returns `ExecutorResult(success=False, error_message="manual executor — no automatic execution")`. Used when `--execute` is absent; preserves V2 behavior.

Decision: The `` executor type is spec'd but should be implemented as a *variant* of `CommandExecutor` with a specific command template (`clawd run --task {task_path} --cwd {run_dir} --timeout {timeout}`). This avoids a separate class and tests focus on the generic command path. It can be broken out later if `` needs special handling.

Core orchestration function:

- `load_executor_config(config_path=None, cli_overrides=None) -> dict` — loads and validates JSON config, merges CLI overrides.
- `validate_executor_config(config) -> list[str]` — checks for unknown template variables, required fields, valid types.
- `create_executor(config) -> Executor` — factory function.
- `execute_workers(manifest, status, run_dir, executor, concurrency=1, only=None, retry_failed=False, timeout=1800) -> dict` — the main loop:
  1. Load manifest, reconcile status (including stale running).
  2. Materialize tasks if missing (calls `tasks.materialize_tasks`).
  3. Build eligible queue: `pending`/`missing` by default; add `failed` if `retry_failed`; filter by `only`.
  4. Process queue with bounded concurrency (`concurrent.futures.ThreadPoolExecutor` with `max_workers=concurrency`, or sequential loop for `concurrency=1`).
  5. Per chunk: create attempt → mark running → launch executor → validate result → mark done/failed → save status.
  6. Handle SIGINT/SIGTERM: stop scheduling new workers, wait for running workers, save final status.
  7. Return execution summary dict.

Design notes:

- Concurrency 1 uses a simple sequential loop (no thread pool overhead). Concurrency >1 uses `ThreadPoolExecutor`. Both share the same per-worker logic.
- Status is saved after each chunk completion (not batched) so interruption loses at most one in-flight result.
- `concurrent.futures` is stdlib; no external deps needed.
- Template variable validation happens before any chunk is marked running. If config is invalid, exit with error and zero state changes.

#### 3b. CLI changes

- `gutenberg orchestrate <run-dir> --execute` stops returning error code 1. Instead, invokes `execute_workers`.
- New flags on `orchestrate`: `--executor <name>`, `--executor-config <path>`, `--concurrency <n>`, `--timeout-seconds <n>`, `--retry-failed`, `--only <chunk-id>` (repeatable).
- New convenience alias: `gutenberg execute <run-dir> [OPTIONS]` — equivalent to `gutenberg orchestrate <run-dir> --execute [OPTIONS]`.
- `--dry-run` remains the default when `--execute` is absent. All existing V2 behavior preserved.

#### 3c. Signal handling

- Register `signal.signal(signal.SIGINT, handler)` and `signal.signal(signal.SIGTERM, handler)` at the start of `execute_workers`.
- On signal: set a `_shutdown` flag, stop dequeuing new chunks, wait for current workers to finish (with a short grace timeout), save status, exit with code 130 (SIGINT convention).
- No `os.kill` of child processes — `subprocess.run` with timeout handles cleanup.

#### 3d. Tests (~30–35 tests)

- `test_command_executor_file_mode` — executor runs command, result file written.
- `test_command_executor_stdout_mode` — executor captures stdout to result path.
- `test_command_executor_timeout` — timeout triggers failure.
- `test_command_executor_nonzero_exit` — exit code recorded.
- `test_command_executor_missing_binary` — clear error before state changes.
- `test_manual_executor_no_launch` — returns failure, prints instructions.
- `test_load_executor_config_valid/invalid` — config loading/validation.
- `test_validate_config_unknown_template_var` — rejected.
- `test_create_executor_factory` — correct type returned.
- `test_execute_workers_pending_only` — launches only pending/missing.
- `test_execute_workers_skips_done` — done chunks untouched.
- `test_execute_workers_skips_failed_by_default` — failed chunks need `--retry-failed`.
- `test_execute_workers_retry_failed` — failed chunks re-queued.
- `test_execute_workers_only_filter` — `--only` limits scope.
- `test_execute_workers_concurrency_bound` — never exceeds max_workers.
- `test_execute_workers_records_attempts` — attempt data in status.
- `test_execute_workers_validates_result` — empty/invalid results → failed.
- `test_execute_workers_materializes_tasks` — auto-creates task files when missing.
- `test_execute_workers_config_validation_before_launch` — invalid config → no state changes.
- `test_cli_orchestrate_execute` — integration test.
- `test_cli_execute_alias` — `gutenberg execute` works.
- `test_cli_orchestrate_dry_run_unchanged` — V2 compatibility.
- `test_orchestrate_json_with_execute` — JSON output after execution.
- `test_signal_handling` — SIGINT stops scheduling (may need careful test design).

---

### Slice 4: Spec 13 — Synthesis Execution

**New file:** `src/gutenberg/synthesis.py`
**Extended:** `cli.py`, `status.py`, `validation.py`
**New tests:** `tests/test_synthesis.py`

#### 4a. `synthesis.py` module

Core functions:

- `check_synthesis_readiness(manifest, status, run_dir) -> dict` — returns `{ready, blockers, state, input_chunks, available_results, missing_chunks}`. Enhanced version of existing `check_synthesis` in `orchestration.py`. States: `not_started`, `blocked`, `ready`, `running`, `done`, `failed`, `partial`.
- `build_synthesis_inputs(manifest, status, run_dir) -> list[dict]` — builds ordered list of worker result entries with availability, path, chunk_id.
- `execute_synthesis(manifest, status, run_dir, executor, partial=False, force=False, timeout=1800) -> dict` — runs synthesis:
  1. Check readiness (refuse if not ready and not `--partial`).
  2. Refuse if `results/synthesis.md` exists and non-empty unless `--force`.
  3. Regenerate `tasks/synthesis.md` with current availability (calls `tasks.generate_synthesis_task`).
  4. Create synthesis attempt record.
  5. Mark synthesis `running` in status.
  6. Launch executor with synthesis task path.
  7. Validate output: exists, non-empty, UTF-8, not whitespace.
  8. Mark `done` or `partial` or `failed`.
  9. Save status.
  10. Return result summary.

#### 4b. Status extensions

Add `status["synthesis"]` top-level entry:

```python
{
  "state": "not_started",  # not_started | blocked | ready | running | done | failed | partial
  "result_path": "results/synthesis.md",
  "task_path": "tasks/synthesis.md",
  "partial": False,
  "input_chunks": 0,
  "available_results": 0,
  "missing_chunks": [],
  "attempts": [],
}
```

V2 status files without `"synthesis"` key are valid; synthesis state is inferred as `not_started` or by checking filesystem.

#### 4c. CLI additions

New subcommand: `gutenberg synthesize <run-dir> [--execute] [--partial] [--force] [--executor <name>] [--executor-config <path>] [--json]`

Optional integration in `gutenberg orchestrate <run-dir> --execute --synthesize` — runs workers first, then synthesis if workers all succeed and synthesis is ready.

#### 4d. Validation extensions

- `synthesis_status_consistency` — if status says done/partial, result file must exist and be non-empty.
- `synthesis_completeness` — done synthesis should have all chunks available.

#### 4e. Tests (~25 tests)

- `test_check_readiness_all_done` — ready.
- `test_check_readiness_pending` — blocked with reason.
- `test_check_readiness_failed` — blocked.
- `test_check_readiness_skipped` — blocked unless partial.
- `test_build_synthesis_inputs_order` — manifest order preserved.
- `test_execute_synthesis_full` — executor runs, result written, state done.
- `test_execute_synthesis_partial` — partial flag, gap metadata recorded.
- `test_execute_synthesis_refuses_incomplete` — no `--partial`, refuses.
- `test_execute_synthesis_refuses_overwrite` — existing file, no `--force`.
- `test_execute_synthesis_force` — overwrites existing.
- `test_execute_synthesis_empty_result` — fails.
- `test_execute_synthesis_records_attempts` — attempt data.
- `test_synthesis_status_v2_compat` — V2 status files work.
- `test_cli_synthesize_dry_run` — readiness check, no mutation.
- `test_cli_synthesize_execute` — integration test.
- `test_cli_orchestrate_synthesize` — `--synthesize` integration.
- `test_validate_synthesis_consistency` — validation catches inconsistencies.

---

### Slice 5: Spec 15 — Run Artifacts, Logs, and Reporting

**New file:** `src/gutenberg/reporting.py`
**Extended:** `cli.py`, `validation.py`, `executor.py` (log capture)
**New tests:** `tests/test_reporting.py`

#### 5a. Log infrastructure (woven into executor.py in Slice 3)

- `executor.py` gains log capture: each `CommandExecutor.launch` writes bounded stdout/stderr to `logs/workers/{chunk_id}.attempt-{NNN}.log`.
- Log size cap: 512KB per attempt (configurable via `executor.max_log_bytes`). Truncate with marker.
- Total run log cap: 5MB default. When exceeded, oldest attempt logs are tail-truncated.
- Synthesis log path: `logs/synthesis/attempt-{NNN}.log`.
- Log functions: `capture_log(content, path, max_bytes)`, `enforce_run_log_cap(run_dir, max_bytes)`.

Note: Log capture code lives in `executor.py` (near the subprocess call) but reporting reads logs from disk. Clean boundary.

#### 5b. Event log

- `reporting.py` provides `append_event(run_dir, event_dict)` — appends one JSON line to `logs/events.jsonl`.
- Events are appended from `execute_workers` and `execute_synthesis` — not from reporting commands.
- Event types: `worker_started`, `worker_done`, `worker_failed`, `worker_skipped`, `worker_retried`, `synthesis_started`, `synthesis_done`, `synthesis_failed`, `run_started`, `run_completed`.
- Each event has `timestamp`, `event`, and context fields (`chunk_id`, `attempt`, `state`, `reason`, etc.).

#### 5c. `orchestration.json`

- Written/updated by `execute_workers` and `execute_synthesis`.
- `build_orchestration_summary(manifest, status, run_dir, executor_config) -> dict` — assembles the summary.
- Updated after each execution pass (workers or synthesis).
- Paths are relative to run directory.

#### 5d. `reporting.py` module

Core functions:

- `build_report(manifest, status, run_dir) -> dict` — assembles report data: source metadata, chunk counts by state, attempt/retry summary, synthesis state, executor info (from orchestration.json if present), key artifact paths.
- `format_report_markdown(report) -> str` — renders the report dict as structured markdown.
- `format_report_json(report) -> dict` — returns the report dict (already JSON-serializable).
- `write_reports(report, run_dir) -> tuple[Path, Path]` — writes `reports/run-report.md` and `reports/run-report.json`.

Reports work for V1/V2 runs too — they use what's available (manifest, status, filesystem) and skip V3-only sections when artifacts are absent.

#### 5e. CLI additions

New subcommand: `gutenberg report <run-dir> [--json] [--markdown] [--write] [--include-validation]`

- Default: human-readable markdown to stdout.
- `--write`: write to `reports/` directory.
- `--json`: machine-readable output.
- `--include-validation`: run `validate_run` and include results.

#### 5f. Validation extensions

- Check `orchestration.json` is valid JSON when present.
- Check `logs/events.jsonl` exists if referenced by orchestration summary.
- Check attempt log paths referenced by status/orchestration exist.
- Check report JSON is valid when present.
- Check no dangling artifact references.

#### 5g. Tests (~25 tests)

- `test_append_event` — writes valid JSONL.
- `test_event_ordering` — events in chronological order.
- `test_build_orchestration_summary` — correct fields.
- `test_build_report_full_run` — all sections populated.
- `test_build_report_v1_run` — works without V3 artifacts.
- `test_build_report_v2_run` — works without V3 artifacts.
- `test_build_report_partial_run` — failed/skipped noted.
- `test_format_report_markdown` — valid markdown, key sections.
- `test_format_report_json` — valid JSON.
- `test_write_reports` — files on disk.
- `test_log_capture_bounded` — truncation at 512KB.
- `test_run_log_cap` — total cap enforcement.
- `test_log_truncation_marker` — marker present.
- `test_cli_report_default` — human output.
- `test_cli_report_json` — JSON output.
- `test_cli_report_write` — files created.
- `test_cli_report_include_validation` — validation summary included.
- `test_validate_orchestration_json` — validation catches invalid.
- `test_validate_dangling_log_refs` — flags missing log files.
- `test_no_secrets_in_logs` — env values redacted.

---

### Implementation Dependencies

```
Slice 1 (tasks) ← independent, implement first
Slice 2 (lifecycle) ← independent of tasks, can parallelize
Slice 3 (executor) ← depends on tasks + lifecycle
Slice 4 (synthesis) ← depends on executor + lifecycle
Slice 5 (reporting) ← depends on executor; log capture woven into slice 3
```

Parallelizable pairs: Slice 1 + Slice 2 can be built simultaneously.
Critical path: Slice 1 → Slice 3 → Slice 4 → Slice 5 (with Slice 2 merging at Slice 3).

### Estimated Test Counts

| Slice | Spec | New Tests | Cumulative |
|-------|------|-----------|------------|
| 1     | 14   | ~25–30    | ~191–196   |
| 2     | 12   | ~30–35    | ~221–231   |
| 3     | 11   | ~30–35    | ~251–266   |
| 4     | 13   | ~25       | ~276–291   |
| 5     | 15   | ~25       | ~301–316   |

### V2 Compatibility Invariants (checked per-slice)

- `gutenberg ingest` unchanged.
- `gutenberg status` works on V1/V2 runs.
- `gutenberg validate` works on V1/V2 runs.
- `gutenberg orchestrate <run>` (no `--execute`) remains non-mutating dry-run.
- V2 `status.json` loads without error.
- Manifest schema additions are additive only.

### Open Questions (to resolve during implementation)

1. **Section validation strictness.** Spec 12 allows warning-only initially. Should the flag to enable strict section validation (`--strict-sections`?) be a V3 launch item or deferred?
   - *Recommendation:* warning-only for V3.0, with `validate_worker_result` returning `(valid=True, warnings=[...])` so the infrastructure is ready.

2. **Concurrency model for >1.** `ThreadPoolExecutor` works for subprocess-based executors but each worker holds a thread. For 9 chunks this is fine. For 50+ chunks, consider `ProcessPoolExecutor` or async — but this is speculative. Recommend `ThreadPoolExecutor` for V3.0.
   - *Recommendation:* ThreadPoolExecutor, reassess if chunk counts exceed ~20.

3. **Manifest mutation on task materialization.** Spec 14 suggests manifest *may* include task metadata. Writing manifest during `gutenberg tasks` creates a side effect. Alternatively, task metadata lives only in `tasks/index.json` and is never written to manifest.
   - *Recommendation:* Do not mutate manifest during `gutenberg tasks`. Task index is the authoritative source. Manifest gains task metadata only during `gutenberg ingest` (future V3.1) or via an explicit `--update-manifest` flag.

4. **`gutenberg execute` alias vs standalone.** Spec 11 says `gutenberg execute` is a convenience alias for `gutenberg orchestrate --execute`. Implementation: a thin CLI alias that sets `args.execute = True` and delegates to `_run_orchestrate`.
   - *Recommendation:* Thin alias. One handler function.

## Verification Gates For V3 Implementation

Before any V3 implementation is considered complete:

- `python -m pytest -q` passes.
- Existing V1/V2 behavior remains compatible.
- `gutenberg orchestrate <run>` dry-run remains non-mutating.
- No command launches external agents unless explicit `--execute` is supplied.
- Worker execution never relaunches completed chunks unless an explicit force/retry option is used.
- Empty, missing, or malformed worker/synthesis outputs are failures, not successes.
- A real long-text dogfood run produces enough artifacts for a human to reconstruct what happened.
