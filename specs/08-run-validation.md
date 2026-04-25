# Spec 08: Run Validation

The run validation system verifies integrity and completeness of a run directory.

## Problem

V1 has no CLI command to check whether a run directory is well-formed, whether all expected files exist, whether the manifest matches the actual chunks, or whether results are complete. Users must manually verify each piece. This blocks confident synthesis and makes debugging failed runs harder.

## Requirements

### CLI: `gutenberg validate <run-dir>`

- Validates structural integrity of a run directory.
- Checks performed:
  1. `manifest.json` exists and is valid JSON matching the manifest schema.
  2. Every chunk file listed in the manifest exists on disk.
  3. Chunk file SHA-256 hashes match manifest values (detects corruption or edits).
  4. Prompt files exist (orchestrator, worker prompts, synthesis prompt).
  5. If `status.json` exists, it is valid and consistent with filesystem state.
  6. If result files exist, they are non-empty markdown.
- Reports each check as pass/fail with details on failures.
- Exit code 0 if all checks pass, non-zero if any fail.

### Validation Levels

- `--strict`: All checks including hash verification (default).
- `--quick`: Skip hash verification for speed on large runs.

### Output

- Human-readable by default: one line per check, summary at end.
- `--json` flag for machine-readable output.
- Failed checks include the specific file path and expected vs actual values.

### Integration with Status

- If `status.json` is absent, validation still works (checks manifest + filesystem only).
- If `status.json` is present, validation cross-checks it against actual filesystem state and reports inconsistencies (e.g., status says `done` but result file is missing).

### Compatibility

- Works on V1 runs (no `status.json`, just manifest + chunks + prompts).
- Does not modify the run directory — validation is read-only.

## Acceptance Criteria

- `gutenberg validate <run>` on a correctly ingested V1 run passes all checks.
- Deleting a chunk file causes validation to fail with a clear error identifying the missing file.
- Corrupting a chunk file (changing content) causes hash check to fail in strict mode but pass in quick mode.
- Missing `manifest.json` produces a clear early failure.
- `--json` output is valid JSON with per-check results.
- Validation on a run with `status.json` reports status/filesystem inconsistencies.
