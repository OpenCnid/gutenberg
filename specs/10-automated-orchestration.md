# Spec 10: Automated Orchestration

The orchestration system automates the worker-to-synthesis pipeline with tracking and resume capability.

## Problem

V1 requires manually spawning each worker agent, manually checking results, and manually running synthesis. The Frankenstein dogfood (9 chunks, only 3 workers run) showed this is tedious even at small scale. At real scale (50+ chunks), manual orchestration is impractical.

V2 needs to automate what was proven manually: spawn workers for each chunk, track their completion, and trigger synthesis when all results are ready.

## Requirements

### CLI: `gutenberg orchestrate <run-dir>`

- Automates the full worker-to-synthesis pipeline for a run.
- Discovers all chunks from the manifest.
- Checks status of each chunk (uses `status.json` from spec 07).
- For each `pending` or `failed` chunk: generates the worker command/prompt and prints it.
- Default mode is `--dry-run`: shows what would be done without executing.
- `--execute` mode actually spawns workers (future, may require agent integration).

### Orchestration Plan Output

- `gutenberg orchestrate <run-dir>` (dry-run) outputs a structured plan:
  - Which chunks need workers (pending/failed).
  - Which chunks are already done (skipped).
  - The exact command or prompt for each pending worker.
  - Whether synthesis is ready (all chunks done) or blocked (listing missing).
- Plan output is human-readable by default, `--json` for machine-readable.

### Resume Capability

- Running `gutenberg orchestrate` on a partially-complete run only processes remaining chunks.
- Already-done chunks are skipped (not re-run).
- Failed chunks are retried unless `--skip-failed` is passed.
- Resume is the default behavior — orchestration is idempotent.

### Synthesis Readiness

- `gutenberg orchestrate --synthesis-check <run-dir>` reports whether synthesis can proceed.
- Synthesis is ready when all chunks have `done` status.
- If not ready, reports which chunks are blocking and their states.
- When ready, outputs the synthesis prompt/command.

### Worker Script Generation

- `gutenberg orchestrate <run-dir> --script` generates a shell script that runs all pending workers sequentially.
- The script uses the worker prompts already generated in the run directory.
- Each worker invocation in the script is a standalone command (copy-pasteable).
- Script includes status update calls after each worker completes.

### Status Integration

- Orchestration reads and writes `status.json` (spec 07).
- Before spawning a worker: marks chunk as `running`.
- After worker completes: marks chunk as `done` or `failed`.
- All state transitions are timestamped.

### Constraints

- V2 orchestration generates commands and scripts — it does not directly call  or any agent API.
- Agent integration (actually spawning sub-agents) is out of scope for V2. The output is commands humans or wrapper scripts execute.
- Orchestration must work offline (no network calls).
- Python stdlib only.

## Acceptance Criteria

- `gutenberg orchestrate <run>` on a fresh run lists all chunks as needing workers.
- `gutenberg orchestrate <run>` on a partial run (3 of 9 done) lists only the 6 remaining chunks.
- `--synthesis-check` on a complete run reports "ready" and outputs the synthesis command.
- `--synthesis-check` on a partial run reports "not ready" with specific blockers.
- `--script` generates a valid shell script with one command per pending worker.
- Resume: running orchestrate twice on the same run does not duplicate work for done chunks.
- Dry-run mode (default) makes no changes to the run directory.
- `--json` output is valid JSON for all orchestration commands.
