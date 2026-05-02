# Implementation Plan — Gutenberg V3

> **Status:** V1 complete. V2 complete. **V3 complete.** All 5 specs (11-15) implemented. Post-V3 hardening pass complete.
> **Last updated:** 2026-05-02
> **Current baseline:** 382 tests passing (confirmed 2026-05-02).
> **Latest validation commits:** Tag: `0.10.0` → `0.11.0`.
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

### V3 Summary

- **All 5 V3 specs implemented** in recommended order (14 → 12 → 11 → 13 → 15).
- **New modules:** `tasks.py`, `lifecycle.py`, `executor.py`, `synthesis.py`, `reporting.py`.
- **Extended:** `paths.py`, `status.py`, `cli.py`, `validation.py`.
- **New CLI commands:** `tasks`, `mark`, `retry`, `skip`, `execute`, `synthesize`, `report`.
- **Test growth:** 166 (V2) → 330 (V3 core) → 348 (V3 wiring) → 368 (post-V3 hardening).
- **V1/V2 backward compatibility preserved** throughout.

### Post-V3 Hardening (2026-05-02)

Spec compliance audit identified and fixed 5 gaps:

1. **Enhanced reconcile_status (spec 12):** Empty/whitespace-only result files on `done` chunks now transition to `failed` with a validation reason (was: only `missing` for absent files). Stale `running` chunks are now resolved during every status/orchestrate read (was: only during `execute_workers`). Unknown chunks in status (not in manifest) are reported as warnings without crashing.
2. **Run-level log cap (spec 15):** Per-run 5MB log cap with oldest-first truncation. Configurable via `executor.max_log_bytes` (per-attempt) and `executor.max_run_log_bytes` (per-run) in manifest.
3. **Unknown chunk warnings:** Surfaced in `gutenberg status` human output and `gutenberg validate` checks.
4. **Executor stale-running unification:** `resolve_stale_running` folded into `reconcile_status` — no longer called separately in executor. Single reconciliation path for all CLI commands.
5. **max_attempts enforcement in execution (spec 12):** `execute_workers` with `--retry-failed` now respects `max_attempts` — chunks at the limit are not relaunched automatically.
6. **Script generation V3 awareness (spec 10/14):** `gutenberg orchestrate --script` now uses per-chunk task files when available instead of the shared worker prompt.

### Post-V3 Hardening Pass 2 (2026-05-02)

1. **`status --json` per-chunk detail (spec 12):** JSON output now includes full per-chunk state, attempts, error metadata, result/task paths, synthesis status, and warnings — not just summary counts.
2. **`--log-max-bytes` CLI flag (spec 15):** Added to `execute`, `synthesize`, and `orchestrate` commands. Overrides per-attempt log cap. Tests verify truncation behavior.

### Post-V3 Hardening Pass 3 (2026-05-02)

1. **`--synthesize` flag on `execute`/`orchestrate --execute` (spec 13):** Combined worker+synthesis execution. After workers succeed, checks synthesis readiness and runs synthesis automatically if ready. Includes JSON output integration.
2. **`--dry-run` flag on `synthesize` command (spec 13):** Explicit `--dry-run` flag added as required option per spec. Default when `--execute` is absent.
3. **Test growth:** 376 → 382 (6 new tests for both features).

## Remaining Known Items

- **`clawd` executor class:** Accepted in config validation but routes through `CommandExecutor`. Fine per spec since the executor "shells out to the binary."
