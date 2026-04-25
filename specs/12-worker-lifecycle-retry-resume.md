# Spec 12: Worker Lifecycle, Retry, Failure, and Resume

V3 needs a durable worker lifecycle model so executed orchestration can fail visibly, resume safely, and avoid false positives.

## Problem

V2 status tracking is enough for manual runs and orchestration planning, but executable orchestration needs stronger state semantics:

- a worker can be launched and interrupted;
- attempts can fail with reasons;
- retries need bounds;
- skipped chunks should be explicit;
- empty or malformed results must not be treated as done;
- a resumed run must reconcile status with filesystem reality.

## State Model

V3 extends per-chunk states to:

- `pending` — not attempted or explicitly reset for retry.
- `running` — an executor attempt is currently active or was active when Gutenberg was interrupted.
- `done` — a valid non-empty worker result exists for the chunk.
- `failed` — the latest attempt failed or validation rejected the result.
- `missing` — a result was expected but the file is missing.
- `skipped` — the operator explicitly chose not to process this chunk.

`skipped` is a V3 state. It is never inferred silently; it requires an explicit operator action.

Run-level states remain compatible with V2 but should account for `skipped`:

- `ingested` — all chunks pending.
- `in_progress` — some chunks pending/running/done, with more work expected.
- `complete` — all chunks done and synthesis, if required by the command, is done.
- `partial` — at least one chunk is done, but at least one chunk is failed/missing/skipped.

## Status Schema Additions

V3 should extend `status.json` additively. Existing V2 fields remain valid.

Each chunk entry should be able to include:

```json
{
  "state": "failed",
  "result_path": "results/chunk-0001.analysis.md",
  "task_path": "tasks/workers/chunk-0001.worker.md",
  "attempt_count": 2,
  "max_attempts": 3,
  "last_error": {
    "code": "empty_result",
    "message": "Worker produced an empty result file."
  },
  "attempts": [
    {
      "attempt": 1,
      "state": "failed",
      "started_at": "2026-04-24T00:00:00+00:00",
      "ended_at": "2026-04-24T00:01:00+00:00",
      "executor": "command",
      "model": "gpt-5.5",
      "exit_code": 1,
      "result_path": "results/chunk-0001.analysis.md",
      "log_path": "logs/workers/chunk-0001.attempt-001.log",
      "error_code": "executor_exit_nonzero",
      "error_message": "executor exited with code 1"
    }
  ],
  "transitions": []
}
```

Exact field names may vary during implementation, but the data must support:

- current state;
- attempt count;
- max attempts used;
- result path;
- task path when available;
- failure reason;
- timestamps;
- safe executor/model metadata;
- log artifact pointers.

## Transition Rules

Allowed normal transitions:

```text
pending -> running -> done
pending -> running -> failed
pending -> skipped
failed  -> pending  (retry requested)
missing -> pending  (retry requested)
skipped -> pending  (operator unskips/retries)
running -> done     (result exists and validates)
running -> failed   (executor failure, timeout, invalid result, or stale interrupted attempt)
done    -> missing  (result file removed or becomes empty/invalid)
```

Rules:

- `done` requires a valid result file.
- `failed` requires a reason.
- `skipped` requires a reason.
- `missing` may be inferred by reconciliation when status says `done` but the result file is absent.
- `running` entries from interrupted runs must be visible on the next status/orchestrate call.
- A stale `running` attempt should reconcile to `done` if a valid result exists, otherwise to `failed` with an interruption/stale-running reason.

## Result Validation

A worker result is valid when:

- file exists at `results/{chunk_id}.analysis.md`;
- file size is greater than zero;
- file is readable as UTF-8 text;
- file contains markdown content, not only whitespace;
- file includes the required worker sections from Spec 05, or validation reports which sections are missing.

Required worker sections:

```md
# Chunk Summary
# Key Claims / Ideas
# Important Quotes
# Entities / Concepts
# Open Questions
# Connections To Other Chunks
# Synthesis Notes
```

An implementation may initially warn instead of failing on missing sections only if the behavior is explicit in validation output. Empty or unreadable results must always fail.

## CLI Support

### Mark State

```bash
gutenberg mark <run-dir> <chunk-id> <state> --reason "..."
```

Required behavior:

- Supports at least `failed`, `pending`, `missing`, and `skipped`.
- Marking `done` requires an existing valid result file unless a separate explicit force option is implemented.
- `--reason` is required for `failed` and `skipped`.
- Writes a timestamped transition.
- Updates run summary.

### Retry

```bash
gutenberg retry <run-dir> --failed
gutenberg retry <run-dir> --chunk chunk-0003
```

Required behavior:

- Resets selected `failed`/`missing`/`skipped` chunks to `pending`.
- Records retry request metadata.
- Does not delete previous attempts or logs.
- Does not overwrite existing valid result files unless an explicit force option is supplied.
- Respects `max_attempts` unless an explicit override is supplied.

### Skip

```bash
gutenberg skip <run-dir> <chunk-id> --reason "..."
```

Required behavior:

- Marks the chunk `skipped`.
- Records reason and timestamp.
- Excludes it from default execution queues.
- Causes synthesis to require explicit partial-synthesis permission (Spec 13).

### Inspect Failures

```bash
gutenberg status <run-dir> --failures
gutenberg status <run-dir> --json
```

Required behavior:

- Human output includes failed/skipped/missing chunks and last reason.
- JSON output includes per-chunk attempts and error metadata.
- Status remains readable for V2 runs lacking V3 attempt fields.

## Retry Bounds

- Default `max_attempts` is `3` unless configured otherwise.
- Each executor launch increments attempt count.
- A chunk at max attempts is not retried automatically.
- Manual `gutenberg retry` can reset a chunk to pending only with explicit acknowledgement if max attempts has been reached.
- Retry limits apply per chunk, not per run.

## Stale-Running Timeout

- Default stale-running timeout is `1800` seconds (30 minutes) per chunk.
- A chunk marked `running` whose elapsed time exceeds this timeout is reconciled to `failed` with reason `timeout` on the next status/orchestrate read.
- The timeout is configurable via manifest `executor.timeout_seconds` or `--timeout-seconds` CLI flag.
- LLM workers processing 50k+ character chunks need room, but anything past 30 minutes is almost certainly stuck.
- Timed-out chunks follow the same retry/skip flow as any other failure.

## Resume Behavior

A resumed executable orchestration run must:

1. Load manifest and status.
2. Reconcile status with filesystem.
3. Resolve stale `running` attempts.
4. Skip valid `done` chunks.
5. Queue eligible `pending`/`missing` chunks.
6. Queue `failed` chunks only when retry options allow it.
7. Preserve previous attempts and logs.

Interrupted runs should not require manual JSON editing to recover.

## Reconciliation Rules

On status/orchestrate/validate reads, Gutenberg should reconcile:

- valid result exists and state is `pending`/`missing`/`running` → `done`;
- state is `done` but result is missing → `missing`;
- state is `done` but result is empty/unreadable/invalid → `failed` with validation reason;
- stale `running` with no valid result → `failed` with `interrupted_or_stale` reason;
- unknown chunks in status → report clearly without crashing;
- manifest chunks missing from status → add compatible entries as `pending` unless filesystem proves `done`.

Reconciliation may update `status.json`, but it must not modify source/chunk/result files.

## Compatibility

- V1 runs without `status.json` still infer status from result files.
- V2 `status.json` files without attempts/reasons remain valid and are upgraded lazily.
- Existing `pending`, `running`, `done`, `failed`, and `missing` values keep their meanings.
- The new `skipped` state is additive.

## Acceptance Criteria

- Fresh ingested runs show all chunks `pending`.
- Starting an executable worker marks the chunk `running` and records an attempt.
- A successful worker with valid output marks the chunk `done`.
- Missing output, empty output, invalid output, timeout, or executor error marks the chunk `failed` with a reason.
- `gutenberg mark <run> chunk-0001 failed --reason "..."` records a failure reason and timestamp.
- `gutenberg retry <run> --failed` resets failed chunks to `pending` without deleting attempt history.
- `gutenberg skip <run> chunk-0002 --reason "..."` marks the chunk `skipped` and excludes it from default execution.
- `gutenberg status <run> --failures` shows failure and skip reasons.
- Interrupted `running` chunks are reconciled on resume and do not stay stuck forever.
- Reconciliation promotes manually written valid result files to `done`.
- Reconciliation demotes missing/empty/invalid `done` results to `missing` or `failed` as appropriate.
- Retry bounds prevent unbounded loops.
- V2 status files continue to load and summarize correctly.
