# Spec 07: Run Status Tracking

The run status tracking system monitors worker result completion state per chunk in a run.

## Problem

V1 has no way to know which chunks have been analyzed, which are pending, and which failed. Users must manually inspect the filesystem to determine run progress. At scale (dozens or hundreds of chunks), this is unworkable.

## Requirements

### Status File

- Each run directory gets a `status.json` file alongside `manifest.json`.
- `status.json` tracks the state of each chunk's worker result.
- Per-chunk states: `pending`, `running`, `done`, `failed`, `missing`.
- Initial state after ingestion: all chunks `pending`.
- Status file includes run-level summary: total chunks, counts per state, overall run state.
- Run-level states: `ingested` (all pending), `in_progress` (some done/running), `complete` (all done), `partial` (some done, some failed/missing).

### Status Updates

- Status transitions are recorded with timestamps (ISO 8601).
- A chunk moves to `done` when its result file exists and is non-empty.
- A chunk moves to `failed` when explicitly marked by orchestration or validation.
- `missing` means expected but no result file found (distinct from `pending` which means not yet attempted).
- Status file is the single source of truth for run progress.

### CLI: `gutenberg status <run-dir>`

- Prints human-readable summary of run progress.
- Shows per-chunk state with chunk index and filename.
- Shows run-level summary (e.g., "5 of 9 done, 2 pending, 2 failed").
- Exit code 0 if run is `complete`, non-zero otherwise.
- Machine-readable output available via `--json` flag.

### Compatibility

- V1 runs that lack `status.json` should still work: `gutenberg status` infers state from filesystem (result file exists → done, else pending).
- Ingestion (`gutenberg ingest`) creates `status.json` automatically for new runs.
- Status file format is JSON, machine-readable, same conventions as `manifest.json`.

## Acceptance Criteria

- After ingestion, `gutenberg status <run>` shows all chunks as `pending`.
- After placing a worker result file for chunk 3, `gutenberg status <run>` shows chunk 3 as `done`.
- `gutenberg status <run> --json` outputs valid JSON matching the status schema.
- V1 runs without `status.json` produce a valid inferred status report.
- Status file records timestamps for each state transition.
