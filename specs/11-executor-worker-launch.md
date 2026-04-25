# Spec 11: Executor / Worker Launch Integration

V3 turns Gutenberg orchestration from a plan/script generator into an explicit, resumable worker launcher while preserving the manual and dry-run paths that made V1/V2 safe.

## Problem

V2 can identify which chunks need workers and can print commands/scripts for a human to run. It does not actually launch workers. This keeps V2 safe, but it leaves large runs bottlenecked on manual copy/paste orchestration.

V3 needs a safe execution layer that can launch worker tasks, bound concurrency, record lifecycle state, and verify outputs without hiding external agent calls or losing the artifact-first contract.

## Scope

This spec covers worker launch execution only. Synthesis execution is specified separately in Spec 13.

V3 execution must remain optional. A default `gutenberg orchestrate <run-dir>` call still behaves as a non-mutating dry-run plan.

## Command Shape

The canonical execution command is:

```bash
gutenberg orchestrate <run-dir> --execute [OPTIONS]
```

Required options:

- `--execute`: required for any external worker launch.
- `--dry-run`: remains available and non-mutating; dry-run is the default when `--execute` is absent.
- `--executor <name>`: selects an executor type or configured executor profile.
- `--executor-config <path>`: optional JSON config file for executor settings.
- `--concurrency <n>`: maximum workers running at once; default `1`.
- `--timeout-seconds <n>`: per-worker timeout; default `1800` (30 minutes). Configurable via CLI flag or manifest `executor.timeout_seconds`.
- `--retry-failed`: include failed chunks in the execution queue.
- `--skip-failed`: preserve V2 planning behavior for explicitly skipping failed chunks.
- `--only <chunk-id>`: optional repeatable chunk filter for targeted execution.

V3 also ships a convenience alias:

```bash
gutenberg execute <run-dir> [OPTIONS]
```

`gutenberg execute <run-dir>` is equivalent to `gutenberg orchestrate <run-dir> --execute`. Both forms are valid; `gutenberg orchestrate <run-dir> --execute` is the canonical form in specs and acceptance tests, but `gutenberg execute` is the expected daily-use command.

## Executor Model

Execution is mediated through an executor abstraction. Gutenberg remains a file-based CLI; it should not require a database, web server, or Python dependency on any external agent internals.

### Executor Protocol

All executor types implement a single Python protocol:

```python
class ExecutorResult:
    success: bool
    exit_code: int | None
    error_message: str | None
    log_path: str | None

class Executor(Protocol):
    def launch(self, task_path: str, result_path: str, timeout: int) -> ExecutorResult: ...
```

The executor receives the materialized task file path (from Spec 14), the expected result file path, and a timeout in seconds. It returns a structured result. Swapping between `command`, `openclaw`, and `manual` executors is a config change, not a code change.

### Executor Types

Minimum required executor types:

1. **`command` executor**
   - Runs a local command template through Python stdlib process APIs.
   - Can be tested with fake local commands.
   - Supports either:
     - executor writes directly to the expected result path, or
     - executor writes markdown to stdout and Gutenberg writes it to the expected result path.

2. **`openclaw` executor**
   - Launches workers via the OpenClaw CLI as a subprocess (`openclaw run --task <task-file> --cwd <run-dir> --timeout <seconds>`).
   - Gutenberg never imports OpenClaw — it shells out to the binary. Clean boundary.
   - Absence of OpenClaw or auth must fail clearly before marking chunks running.
   - No OpenClaw credentials or tokens are stored in Gutenberg run artifacts.

3. **`manual` executor / fallback**
   - Preserves V2 behavior: print or script copy-pasteable tasks without launching anything.
   - This remains the behavior when `--execute` is absent.

## Executor Config

Executor config is JSON. It may live outside the run directory or be copied into the run as a sanitized artifact (see Spec 15).

Example shape:

```json
{
  "executor": {
    "type": "command",
    "command": ["agent-cli", "--task", "{task_path}"],
    "output_mode": "stdout",
    "model": "gpt-5.5",
    "timeout_seconds": 1800,
    "concurrency": 2
  }
}
```

Template variables available to executors:

- `{run_dir}`
- `{chunk_id}`
- `{chunk_path}`
- `{task_path}`
- `{result_path}`
- `{worker_prompt_path}`

Rules:

- Unknown template variables fail validation before launching anything.
- Config must not require secrets in JSON.
- Environment variable values are never written to logs or artifacts.
- Relative paths in config resolve from the current working directory unless explicitly documented otherwise.

## Launch Eligibility

Before launching, Gutenberg must load `manifest.json`, reconcile `status.json` with the filesystem, and materialize task files if Spec 14 is implemented.

Eligible by default for `--execute`:

- `pending`
- `missing`

Eligible only with explicit options:

- `failed` with `--retry-failed`
- `skipped` with an explicit retry/mark operation from Spec 12
- `done` only with an explicit force option if such an option is implemented

Never launch by default:

- chunks with a valid non-empty result file
- chunks currently marked `running` unless reconciled as stale/interrupted by Spec 12 rules
- chunks excluded by `--only`

## Worker Output Contract

Each launched worker has exactly one assigned chunk and one expected result path:

```text
results/{chunk_id}.analysis.md
```

A worker attempt succeeds only when:

- the worker process/session exits successfully or reports success through the executor boundary;
- the expected result file exists;
- the result file is non-empty;
- the result file satisfies the minimum worker-result validation rules from Spec 12.

Empty files, missing files, malformed markdown, timeouts, executor errors, or interrupted sessions are failures, not successes.

## Lifecycle Integration

Execution must update `status.json` through the lifecycle rules in Spec 12:

1. Before launch: create an attempt record and mark chunk `running`.
2. During launch: record executor/session/process metadata that is safe to store.
3. On success: mark chunk `done` and record result path, end time, and duration.
4. On failure: mark chunk `failed` and record reason, exit code/session error, and log pointers.

Status writes should be as atomic as practical: write to a temporary file and rename to avoid corrupting `status.json` on interruption.

## Concurrency

- Default concurrency is `1`.
- `--concurrency` must be a positive integer.
- Gutenberg must never run more than the configured number of workers concurrently.
- Completion order may differ from manifest order, but task selection should be deterministic when all else is equal.
- Concurrent workers must not write the same result path.
- `Ctrl-C`/interruption should stop scheduling new workers, attempt graceful shutdown, and leave enough status/log data for `resume` behavior.

## Dry-Run and Script Compatibility

- `gutenberg orchestrate <run-dir>` remains a dry-run plan and must not modify the run directory.
- `--json` remains valid JSON output for plans.
- `--script` remains available as a manual/script fallback.
- V3 script output should be lifecycle-aware when possible, but script generation still must not require OpenClaw availability.

## Safety Requirements

- No external worker launch happens without explicit `--execute`.
- No hidden destructive behavior.
- Completed chunks are not duplicated.
- Failed chunks are not relaunched unless explicitly requested.
- Executor config is validated before any chunk is marked `running`.
- If the executor cannot be initialized, no chunk state changes occur.
- Secret-bearing environment values are not logged.

## Compatibility

- V1/V2 runs without task metadata or V3 status fields still work.
- V3 may add manifest/status fields, but existing required fields remain valid.
- Manual worker result files written outside Gutenberg are still detected by status reconciliation.

## Acceptance Criteria

- `gutenberg orchestrate <run>` without `--execute` is non-mutating and behaves like V2 dry-run planning.
- `gutenberg orchestrate <run> --execute --executor command --concurrency 1` launches workers only for eligible pending/missing chunks.
- Completed chunks with valid result files are skipped and not relaunched.
- Failed chunks are not relaunched unless `--retry-failed` is provided.
- `--only chunk-0003` launches only that chunk when it is eligible.
- `--concurrency 2` never runs more than two workers at once.
- Each worker attempt records lifecycle data in `status.json`.
- Successful workers produce non-empty `results/{chunk_id}.analysis.md` files and transition to `done`.
- Missing, empty, malformed, timed-out, or non-zero-exit worker outputs transition to `failed` with a visible reason.
- Executor initialization failure exits clearly and does not mark chunks `running`.
- `--json` output remains valid JSON for dry-run and execution summary modes.
- V1/V2 manual fallback pathways continue to work.
