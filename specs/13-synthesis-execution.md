# Spec 13: Synthesis Execution

V3 should run the synthesis step through the same safe execution discipline as worker orchestration, instead of only checking readiness.

## Problem

V2 can report whether synthesis is ready and can print the synthesis prompt path. It does not actually execute synthesis or record synthesis lifecycle state.

Once V3 can launch workers, Gutenberg also needs a safe way to run the final synthesis over worker outputs, write `results/synthesis.md`, record status, and make partial synthesis an explicit choice.

## Command Shape

Canonical command:

```bash
gutenberg synthesize <run-dir> [OPTIONS]
```

Required options:

- `--execute`: required to launch an external synthesis executor.
- `--dry-run`: default when `--execute` is absent; reports readiness and planned inputs without writing synthesis output.
- `--executor <name>` and `--executor-config <path>`: same executor model as Spec 11.
- `--partial`: allow synthesis when some chunks are missing/failed/skipped.
- `--force`: allow overwriting an existing non-empty `results/synthesis.md`.
- `--json`: machine-readable output.

Optional integration:

```bash
gutenberg orchestrate <run-dir> --execute --synthesize
```

If implemented, this runs eligible workers first, then runs synthesis only after worker execution and readiness checks pass. The standalone `gutenberg synthesize` command remains the source of truth.

## Readiness Rules

Before synthesis execution, Gutenberg must:

1. Load `manifest.json`.
2. Load/reconcile `status.json`.
3. Validate worker result availability and non-empty content.
4. Build the ordered list of worker result files according to manifest chunk order.
5. Refuse to overwrite an existing non-empty synthesis unless `--force` is supplied.

Default synthesis is allowed only when all manifest chunks are `done` and all expected worker result files are valid.

If any chunk is `pending`, `running`, `missing`, `failed`, or `skipped`, synthesis refuses by default and prints blockers.

`--partial` is required to synthesize with gaps.

## Partial Synthesis

Partial synthesis is explicit. With `--partial`, Gutenberg may synthesize from available valid worker results while preserving gap metadata.

Partial synthesis must:

- list missing, failed, skipped, and still-pending chunks in the synthesis task;
- record partial input coverage in status/artifacts;
- include a `Missing Chunks` or equivalent section in the synthesis instructions;
- avoid marking the run as fully complete;
- make partial status visible in `gutenberg status` and `gutenberg report`.

`--partial` does not ignore invalid result files. Invalid available result files are blockers unless the corresponding chunk is explicitly skipped or otherwise excluded.

## Synthesis Task Input

Synthesis execution should use a concrete synthesis task file from Spec 14 when available:

```text
tasks/synthesis.md
```

The task should include:

- run title/author/source metadata;
- manifest path;
- ordered list of expected worker results;
- ordered list of available worker results;
- missing/failed/skipped blockers or partial-synthesis gap list;
- required output path: `results/synthesis.md`;
- expected synthesis output format.

The executor should receive the synthesis task path, not an ambiguous generic prompt requiring manual substitution.

## Output Contract

Synthesis output path:

```text
results/synthesis.md
```

A synthesis attempt succeeds only when:

- the executor reports success;
- `results/synthesis.md` exists;
- the file is non-empty readable UTF-8 markdown;
- the file is not only whitespace;
- partial/full status is recorded correctly.

If the executor writes to stdout, Gutenberg may write stdout to `results/synthesis.md`. If the executor writes the file directly, Gutenberg must verify it after completion.

## Synthesis Status

V3 should extend `status.json` with a top-level synthesis entry. Existing V2 status files remain valid if the synthesis entry is absent.

Example shape:

```json
{
  "synthesis": {
    "state": "done",
    "result_path": "results/synthesis.md",
    "task_path": "tasks/synthesis.md",
    "partial": false,
    "started_at": "2026-04-24T00:00:00+00:00",
    "ended_at": "2026-04-24T00:02:00+00:00",
    "input_chunks": 9,
    "available_results": 9,
    "missing_chunks": [],
    "attempts": []
  }
}
```

Synthesis states:

- `not_started`
- `blocked`
- `ready`
- `running`
- `done`
- `failed`
- `partial`

Rules:

- `done` means full synthesis completed with all chunks available.
- `partial` means synthesis completed with explicit gaps.
- `failed` requires a reason.
- `blocked` records readiness blockers without launching execution.

## Executor Behavior

Synthesis uses the same executor protocol as Spec 11 (`launch(task_path, result_path, timeout) -> ExecutorResult`):

- validates executor config before state changes;
- records attempt metadata;
- captures safe logs (bounded to 512KB per attempt — see Spec 15);
- redacts secrets;
- respects timeout (default 1800 seconds / 30 minutes);
- writes status atomically where practical.

Synthesis concurrency is always one per run. Multiple simultaneous synthesis attempts for the same run are not allowed.

## Validation Integration

`gutenberg validate <run-dir>` should be able to check synthesis output when present:

- synthesis file exists if status says synthesis is `done` or `partial`;
- synthesis file is non-empty;
- status result path matches expected path;
- full synthesis does not claim completion when worker results are missing.

## Compatibility

- V1/V2 runs without synthesis status remain valid.
- Existing `results/synthesis.md` files from manual runs are detected and can be reported.
- Existing synthesis prompt at `prompts/synthesis.md` remains available.
- Manual synthesis remains possible: a human can still read prompts/results and write `results/synthesis.md` directly.

## Acceptance Criteria

- `gutenberg synthesize <run>` without `--execute` performs a non-mutating readiness check.
- On a complete run, `gutenberg synthesize <run> --execute` runs the configured executor and writes `results/synthesis.md`.
- On an incomplete run, `gutenberg synthesize <run> --execute` refuses by default and lists specific blockers.
- `--partial` allows synthesis with missing/failed/skipped chunks and records partial status.
- Existing non-empty `results/synthesis.md` is not overwritten unless `--force` is supplied.
- Synthesis reads worker results in manifest chunk order, not arbitrary filesystem order.
- Empty, missing, unreadable, or whitespace-only synthesis output fails the attempt.
- Successful full synthesis records synthesis state `done`.
- Successful partial synthesis records synthesis state `partial` and gap metadata.
- Failed synthesis records state `failed`, reason, and log pointers.
- `gutenberg validate` reports inconsistencies between synthesis status and output files.
- V1/V2 manual synthesis output remains readable and reportable.
