# Implementation Plan — Gutenberg V3

> **Status:** V1 complete. V2 complete and dogfood-validated. V3 is in specification/planning only; do **not** implement V3 until specs 11–15 have been reviewed.
> **Last updated:** 2026-04-24
> **Current baseline:** 166 tests passing.
> **Latest validation commits:** `20eeea9`, `bc86c69`, `f2abb05`.
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
- V3 should improve ergonomics by materializing per-chunk worker task files or task payloads with concrete chunk numbers, paths, and result targets.
- V2 script output is an operational scaffold. V3 should replace scaffold/TODO status updates with real lifecycle-aware execution and auditable logs.

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
   - Creates concrete worker task inputs used by execution.
   - Resolves the `{chunk_number}` ergonomics issue without changing V2 semantics.
   - Gives later executor tests stable, deterministic files to assert against.

2. **Spec 12 — Worker Lifecycle, Retry, Failure, and Resume**
   - Extends status semantics before anything launches real workers.
   - Adds attempt records, failure reasons, skipped state, retry bounds, and mark/retry/skip commands.

3. **Spec 11 — Executor / Worker Launch Integration**
   - Uses concrete tasks and lifecycle state to launch only eligible chunks.
   - Adds executor config and bounded concurrency behind explicit `--execute`.

4. **Spec 13 — Synthesis Execution**
   - Runs after worker execution has reliable status and result validation.
   - Adds synthesis state and explicit partial synthesis behavior.

5. **Spec 15 — Run Artifacts, Logs, and Reporting**
   - Can start in parallel as a design concern, but should land after lifecycle/executor primitives exist.
   - Finalizes audit trail, dogfood reporting, and validation/report integration.

## Verification Gates For V3 Implementation

Before any V3 implementation is considered complete:

- `python -m pytest -q` passes.
- Existing V1/V2 behavior remains compatible.
- `gutenberg orchestrate <run>` dry-run remains non-mutating.
- No command launches external agents unless explicit `--execute` is supplied.
- Worker execution never relaunches completed chunks unless an explicit force/retry option is used.
- Empty, missing, or malformed worker/synthesis outputs are failures, not successes.
- A real long-text dogfood run produces enough artifacts for a human to reconstruct what happened.
