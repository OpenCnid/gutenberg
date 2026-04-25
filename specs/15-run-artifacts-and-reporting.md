# Spec 15: Run Artifacts, Logs, and Reporting

Executable V3 runs need an audit trail. A human should be able to reconstruct what happened without reading transient agent transcripts.

## Problem

V2 plans and status are useful, but actual execution introduces more questions:

- Which executor/model launched each worker?
- Which chunks were attempted, retried, skipped, or failed?
- What command/session/log corresponds to a failure?
- Did synthesis run fully or partially?
- Which validation checks passed after the run?

V3 must record enough local artifacts to debug and dogfood runs while avoiding unnecessary private data capture.

## Artifact Layout

V3 execution adds these optional run artifacts:

```text
<run>/
  orchestration.json
  logs/
    events.jsonl
    workers/
      chunk-0001.attempt-001.log
      chunk-0001.attempt-002.log
    synthesis/
      attempt-001.log
  reports/
    run-report.md
    run-report.json
```

Artifacts are created when execution/reporting commands need them. V1/V2 runs without these files remain valid.

## `orchestration.json`

`orchestration.json` is the machine-readable summary of execution for the run.

Minimum fields:

```json
{
  "schema_version": "1.0",
  "run_dir": ".",
  "created_by": "gutenberg",
  "executor": {
    "type": "command",
    "model": "gpt-5.5",
    "concurrency": 2
  },
  "workers": {
    "total": 9,
    "done": 8,
    "failed": 1,
    "skipped": 0
  },
  "synthesis": {
    "state": "blocked",
    "result_path": "results/synthesis.md"
  },
  "artifacts": {
    "events": "logs/events.jsonl",
    "report_markdown": "reports/run-report.md",
    "report_json": "reports/run-report.json"
  }
}
```

Rules:

- Store safe executor metadata, not secrets.
- Paths are relative to the run directory.
- Repeated execution updates the summary instead of overwriting attempt history.
- The file should be valid JSON after each successful write.

## Event Log

`logs/events.jsonl` records append-only lifecycle events.

Each event should include:

- timestamp;
- event type;
- chunk id when applicable;
- synthesis marker when applicable;
- attempt number when applicable;
- state transition when applicable;
- safe executor/session/process identifiers when available;
- message/reason.

Example:

```json
{"timestamp":"2026-04-24T00:00:00+00:00","event":"worker_started","chunk_id":"chunk-0001","attempt":1}
```

Events must be sufficient to reconstruct the order of execution, retries, failures, skips, and synthesis attempts.

## Attempt Logs

Each worker/synthesis attempt should have a log artifact.

Worker log path pattern:

```text
logs/workers/{chunk_id}.attempt-{attempt_number_padded}.log
```

Synthesis log path pattern:

```text
logs/synthesis/attempt-{attempt_number_padded}.log
```

Logs may include:

- sanitized command/session summary;
- executor stdout/stderr when safe;
- timeout/error messages;
- output validation summary;
- result path verification.

Logs must not include:

- environment variable values;
- API tokens;
- auth cookies;
- raw secret-bearing config values;
- unrelated user data outside the run directory.

## Large Artifact Policy

- Default per-attempt log capture is bounded to **512KB** per chunk/synthesis attempt.
- Default total log cap per run is **5MB**. When exceeded, oldest attempt logs are truncated (tail preserved).
- If logs are truncated, include a clear truncation marker with original and truncated byte counts.
- Log size limits are configurable via manifest `executor.max_log_bytes` (per-attempt) and `executor.max_run_log_bytes` (per-run), or CLI `--log-max-bytes <n>`.
- Logs are metadata, not results — if they exceed these limits, something is likely wrong.
- Large worker/synthesis results are stored in `results/`, not duplicated into logs.
- Reports should summarize large artifacts by path and size rather than embedding full content.

## Reporting Command

Canonical command:

```bash
gutenberg report <run-dir> [OPTIONS]
```

Required options:

- `--json`: print machine-readable report.
- `--markdown`: print markdown report (default human output may also be markdown).
- `--write`: write `reports/run-report.md` and `reports/run-report.json`.
- `--include-validation`: run or include latest validation summary.

A report should summarize:

- source title/author/character count;
- chunk count;
- worker state counts: pending/running/done/failed/missing/skipped;
- attempt counts and retry summary;
- failed/skipped chunks with reasons;
- synthesis state and output path;
- partial-synthesis gaps if any;
- validation state;
- executor/model/concurrency metadata;
- key artifact paths.

## Dogfood Reporting

The reporting output should be suitable for a real dogfood pass. A human should be able to answer:

- What source was processed?
- How many chunks were created?
- Which commands or executor profiles were used?
- Which chunks succeeded, failed, or were skipped?
- Did resume avoid duplicate work?
- Did synthesis run, and was it full or partial?
- Did validation pass after execution?
- What were the important bugs/friction points?

The command does not need to invent narrative analysis; it should produce accurate operational facts and leave a place for human notes when written to markdown.

## Validation Integration

`gutenberg validate <run-dir>` should be able to validate V3 artifacts when present:

- `orchestration.json` is valid JSON;
- event log exists if orchestration summary references it;
- attempt log paths referenced by status/orchestration exist;
- report JSON is valid when present;
- report paths are inside the run directory;
- artifacts referenced by status/orchestration are not dangling.

Validation remains read-only.

## Privacy and Safety

- Do not log secret values.
- Do not copy executor config containing secrets into the run directory.
- Do not log full environment dumps.
- Do not include unrelated files outside the run directory.
- Prefer sanitized executor metadata: type, model name, concurrency, timeout, safe session id.
- If a command string may contain secrets, store a redacted command summary instead.

## Compatibility

- V1/V2 runs without V3 artifacts remain valid.
- Reports can be generated for V1/V2 runs using manifest/status/filesystem inference.
- Manual runs can still benefit from `gutenberg report` even if no executor logs exist.
- Artifact schema changes should be additive.

## Acceptance Criteria

- Executing workers creates or updates `orchestration.json` with executor, worker, synthesis, and artifact summary fields.
- Worker attempts write bounded log artifacts under `logs/workers/`.
- Synthesis attempts write bounded log artifacts under `logs/synthesis/`.
- `logs/events.jsonl` records worker start/end/failure/retry/skip and synthesis events in execution order.
- `gutenberg report <run> --write` writes `reports/run-report.md` and `reports/run-report.json`.
- Reports summarize chunks done/failed/skipped/missing, synthesis status, validation state, executor/model info, and retry/failure summaries.
- Reports for V1/V2 runs work even when no V3 execution artifacts exist.
- Large logs are truncated with explicit markers instead of growing unbounded.
- No environment variable values or secret-bearing config values are written to logs/reports.
- `gutenberg validate` reports dangling or invalid V3 artifact references when artifacts are present.
- A human can reconstruct the worker/synthesis lifecycle from `status.json`, `orchestration.json`, `logs/events.jsonl`, and report files.
