# Implementation Plan — Gutenberg V2

> **Status:** Phase 0 + Phase 9 + Phase 10 + Phase 11 complete. V2 implementation in progress.
> **Last updated:** 2026-04-24
> **V2 baseline:** 137 tests, Phase 0 + Phase 9 + Phase 10 + Phase 11 done.
> **V1 baseline:** 57 tests, 6 specs satisfied, all passing.
> **V2 target:** 4 new specs (07–10), ~61+ new tests, full backward compatibility.
> **Schema version:** Stays `"1.0"` — all V2 manifest changes are additive and optional. V1 manifests remain valid with V2 tools.

## V1 Completion Record

- Phase 1–8: Complete. 57/57 tests passing.
- Specs 01–06: All satisfied.
- Dogfood: Validated on Frankenstein (247k chars, 9 chunks, 3 manual workers).
- No TODOs, FIXMEs, or placeholders in codebase.

---

## V2 Overview

Four capabilities driven by Frankenstein dogfood friction:

| Spec | Capability | New module | CLI command |
|------|-----------|------------|-------------|
| 09 | Chunk context enrichment | — (modifies `chunking.py`, `manifest.py`, `prompts.py`) | `--context-chars` on `ingest` |
| 07 | Run status tracking | `status.py` | `gutenberg status <run>` |
| 08 | Run validation | `validation.py` | `gutenberg validate <run>` |
| 10 | Automated orchestration | `orchestration.py` | `gutenberg orchestrate <run>` |

### Implementation Order & Rationale

**09 → 07 → 08 → 10**

1. **Spec 09 first** — Modifies the core data model (`ChunkInfo` dataclass), manifest schema, and prompt templates. Every downstream spec works with the final enriched data structures. No dependencies on other V2 specs.
2. **Spec 07 second** — Adds `status.json` layer. Independent of 09's changes. Needed by 08 (cross-validation) and 10 (state machine).
3. **Spec 08 third** — Validation reads manifest + optionally status. Benefits from both 09 (validates enriched manifest fields) and 07 (cross-checks status).
4. **Spec 10 last** — Orchestration depends heavily on 07 (reads/writes `status.json`) and benefits from 08 (`validate` as pre-flight check).

---

## Phase 0: Version Bump ✅

Complete. Version bumped to `0.2.0` in `__init__.py`, `pyproject.toml`, and test assertion updated.

---

## Phase 9: Chunk Context Enrichment (Spec 09) ✅

Complete. 23 new tests added (80 total). All acceptance criteria met:
- `ChunkInfo` extended with `chunk_index`, `chunk_number`, `total_chunks`, `prev_context`, `next_context`, `inferred_section`.
- Single-chunk early return removed; post-processing applied uniformly.
- `_detect_section()` with conservative regex for CHAPTER/PART/LETTER/BOOK markers.
- Manifest includes all new fields; `inferred_section` omitted when `None`.
- `context_chars` parameter added to `chunk_text()` and `build_manifest()`.
- CLI: `--context-chars` option, frontmatter includes all V2 fields, `json.dumps()` for safe YAML quoting.
- Worker prompt includes chunk position and neighbor context references.
- Synthesis prompt includes bolded chunk count.
- V1 manifests without new fields still validate.

---

## Phase 10: Run Status Tracking (Spec 07) ✅

Complete. 35 new tests added (115 total). All acceptance criteria met:
- `status.py` module with `create_status`, `load_status`, `save_status`, `update_chunk_state`, `infer_status`, `compute_run_state`, `summarize_status`.
- `paths.py` extended with `STATUS_FILENAME` and `status_path()`.
- `status.json` created automatically during `gutenberg ingest`.
- `gutenberg status <run-dir>` CLI subcommand with `--json` flag.
- Exit code 0 when complete, 1 otherwise.
- V1 backward compatibility via `infer_status` (filesystem scan).
- ISO 8601 timestamps on all state transitions.
- Per-chunk states: pending, running, done, failed, missing.
- Run-level states: ingested, in_progress, complete, partial.

---

## Phase 11: Run Validation (Spec 08) ✅

Complete. 22 new tests added (137 total). All acceptance criteria met:
- `validation.py` module with `validate_run()` returning per-check results.
- Checks: manifest schema, source file, chunk files, SHA-256 hashes (strict), prompt files, status.json consistency, results directory, non-empty result files.
- Per-chunk SHA-256 added to manifest via `chunk_hashes` parameter in `build_manifest()`.
- Hashes computed from full chunk file content (frontmatter + title + body) in `_run_ingest()`.
- `gutenberg validate <run-dir>` CLI with `--strict` (default), `--quick`, `--json`.
- Exit code 0 when all pass, 1 when any fail.
- V1 manifests without SHA-256 field: hash check skipped gracefully.
- Read-only: validation never modifies the run directory.

---

## Phase 12: Automated Orchestration (Spec 10)

**Goal:** Automate worker-to-synthesis pipeline with tracking and resume.

### Task 12.1: Create `orchestration.py` module

**File:** `src/gutenberg/orchestration.py` (new)

Functions:

- `build_plan(manifest: dict, status: dict, skip_failed: bool = False) -> dict` — Analyze chunks, classify into `pending`, `done`, `failed`, `skip`. Returns structured plan: `{pending: [...], done: [...], failed: [...], skipped: [...], synthesis_ready: bool, blockers: [...]}`.
- `format_worker_command(run_dir: Path, chunk: dict) -> str` — Generate the shell command / prompt text for one worker. Uses the worker prompt file path and chunk file path from the run directory.
- `format_plan_text(plan: dict, run_dir: Path) -> str` — Human-readable plan output.
- `format_plan_json(plan: dict, run_dir: Path) -> dict` — Machine-readable plan.
- `generate_script(plan: dict, run_dir: Path) -> str` — Shell script with one command per pending worker, plus status update calls.
- `check_synthesis(plan: dict, manifest: dict, run_dir: Path) -> dict` — Report whether synthesis is ready, list blockers, output synthesis command if ready.

**Depends on:** 10.1 (status module).

### Task 12.2: Add `gutenberg orchestrate` CLI subcommand

**File:** `src/gutenberg/cli.py`

In `_build_parser()`:
- Add `orchestrate` subcommand with positional `run-dir`.
- Flags: `--dry-run` (default, implicit), `--execute` (future, prints warning that it's not implemented in V2), `--synthesis-check`, `--script`, `--skip-failed`, `--json`.

New function `_run_orchestrate(args) -> int`:
1. Load manifest and status (or infer status for V1 runs).
2. Build orchestration plan.
3. Dispatch based on flags:
   - Default (dry-run): print plan showing pending/done/failed chunks and commands.
   - `--synthesis-check`: report readiness and synthesis command.
   - `--script`: output shell script to stdout.
   - `--json`: machine-readable output for any mode.
4. Dry-run mode makes no changes to the run directory.
5. Exit code: 0 normally, 1 if synthesis not ready (for `--synthesis-check`).

**Depends on:** 12.1.

### Task 12.3: Status integration in orchestration

**File:** `src/gutenberg/orchestration.py`

When `--execute` is eventually implemented (out of V2 scope), the orchestrator would:
1. Mark chunk as `running` before spawning.
2. Mark chunk as `done` or `failed` after completion.

For V2 dry-run:
- Read status, don't write.
- The generated shell script includes comments showing where status updates would go.

For the `--script` output:
- Include `# TODO: update status.json after each worker` comments.
- Or generate actual `gutenberg status-update` calls if we add that subcommand (stretch — probably not V2).

**Depends on:** 12.1, 10.1.

### Task 12.4: Tests for spec 10

**File:** `tests/test_orchestration.py` (new)

Tests (~16):
- Fresh run (all pending): plan lists all chunks as needing workers.
- Partial run (3 of 9 done): plan lists only 6 remaining.
- Complete run: plan shows all done, synthesis ready.
- `--synthesis-check` on complete run: reports ready + synthesis command.
- `--synthesis-check` on partial run: reports not ready + specific blockers.
- `--skip-failed`: failed chunks excluded from plan.
- `--script` generates valid shell script with one command per pending worker.
- Resume: orchestrate twice → second run skips done chunks (idempotent).
- Dry-run mode makes no changes to run directory.
- `--json` output is valid JSON.
- Worker commands reference correct file paths.
- V1 run without `status.json`: works via inferred status.
- Plan format includes chunk IDs and file paths.
- Empty run (no chunks) handles gracefully.
- Script output is copy-pasteable (standalone commands).
- `--execute` prints not-implemented warning.
- Orchestrator prompt contains V2 CLI references (after Task 12.5).

**Estimated new tests:** ~17

**Depends on:** 12.1–12.3, 12.5.

### Task 12.5: Update orchestrator prompt for V2 CLI references

**File:** `src/gutenberg/prompts.py`

In `generate_orchestrator_prompt()`, add a section after "Manual Orchestration Steps" that references V2 CLI tools:

```
### V2 CLI Tools (Optional)

If Gutenberg V2 is installed, these commands can help:

- `gutenberg status <run-dir>` — Check completion progress.
- `gutenberg validate <run-dir>` — Verify run integrity.
- `gutenberg orchestrate <run-dir>` — Generate a plan for remaining work.
- `gutenberg orchestrate <run-dir> --script` — Generate a shell script for pending workers.
- `gutenberg orchestrate <run-dir> --synthesis-check` — Check synthesis readiness.
```

Preserve the "no automated" language to satisfy `test_no_automation_claims`. Update the wording from "There is no automated worker spawning in V1" to "There is no automated worker spawning" (drop the "in V1" qualifier since V2 also doesn't auto-spawn — it generates commands only). The test asserts `"automated" not in prompt.lower() or "no automated" in prompt.lower()`, so any sentence containing "no automated" passes.

**Depends on:** 12.1, 12.2 (references the commands they implement).

### Spec 10 Risks & Decisions

- **No agent API calls:** V2 orchestration generates commands/scripts only. `--execute` is stubbed with a clear message.
- **Worker command format:** The generated command should be a generic instruction referencing the worker prompt and chunk file. Format: something like `cat <chunk-file> | <agent-cmd> --prompt <worker-prompt>` or just a textual instruction. Keep it generic since the actual agent CLI varies.
- **Script portability:** Generated scripts assume bash. Include shebang and `set -e`.
- **Offline operation:** No network calls. All data from filesystem.

---

## File Change Summary

| File | Phase | Change Type |
|------|-------|-------------|
| `src/gutenberg/chunking.py` | 9 | Modify: extend `ChunkInfo`, add post-processing, add section detection |
| `src/gutenberg/manifest.py` | 9, 11 | Modify: add chunk fields (position, context, section), add per-chunk SHA-256 |
| `src/gutenberg/prompts.py` | 9 | Modify: position in worker prompt, chunk count in synthesis prompt |
| `src/gutenberg/paths.py` | 10 | Modify: add `STATUS_FILENAME`, `status_path()` |
| `src/gutenberg/__init__.py` | 0 | Modify: version bump `0.1.0` → `0.2.0` |
| `pyproject.toml` | 0 | Modify: version bump `0.1.0` → `0.2.0` |
| `src/gutenberg/cli.py` | 9, 10, 11, 12 | Modify: `--context-chars`, chunk file hash computation, `status`/`validate`/`orchestrate` subcommands |
| `src/gutenberg/status.py` | 10 | **New**: status model and operations |
| `src/gutenberg/validation.py` | 11 | **New**: run validation checks |
| `src/gutenberg/orchestration.py` | 12 | **New**: orchestration planning and script generation |
| `tests/test_chunking.py` | 9 | Extend: position, context, section detection tests |
| `tests/test_manifest.py` | 9, 11 | Extend: new fields, SHA-256, optional field validation |
| `tests/test_prompts.py` | 9, 12 | Extend: position in prompts, chunk count, V2 CLI references in orchestrator prompt |
| `tests/test_cli.py` | 9, 10, 11, 12 | Extend: new subcommands, new ingest options |
| `tests/test_manifest.py` | 0 | Extend: update `test_tool_info` assertion from `0.1.0` to `0.2.0` |
| `tests/test_status.py` | 10 | **New**: status tracking tests |
| `tests/test_validation.py` | 11 | **New**: validation tests |
| `tests/test_orchestration.py` | 12 | **New**: orchestration tests |

## Test Count Projection

| Phase | New Tests | Running Total |
|-------|-----------|---------------|
| V1 baseline | — | 57 |
| Phase 0 (version bump) | 0 (1 test updated) | 57 |
| Phase 9 (Spec 09) | ~16 | ~73 |
| Phase 10 (Spec 07) | ~15 | ~88 |
| Phase 11 (Spec 08) | ~14 | ~102 |
| Phase 12 (Spec 10) | ~17 | ~119 |

## Existing Test Compatibility

Key V1 tests that must not break:

- `test_chunking.py`: `ChunkInfo` field checks — new fields have defaults, no breakage.
- `test_manifest.py`: Manifest structure checks — new fields are additive, `validate_manifest()` doesn't require them.
- `test_prompts.py`: Prompt content checks — prompts gain new content but existing assertions (e.g., "manual" in orchestrator prompt, required sections in worker prompt) remain true.
- `test_cli.py`: Ingest pipeline — output gains `status.json` and richer frontmatter, but existing checks (manifest exists, chunks exist, prompts exist) still pass.

**Tests that need careful attention:**

1. `test_no_automation_claims` in `test_prompts.py` checks `"automated" not in prompt.lower() or "no automated" in prompt.lower()`. The current orchestrator prompt says "There is no automated worker spawning in V1." which satisfies the "no automated" branch. V2 should preserve this language in the orchestrator prompt OR update the test. The worker and synthesis prompts don't mention automation, so they're safe.

2. In Phase 12, the orchestrator prompt template should be updated to reference V2 CLI commands (`gutenberg status`, `gutenberg validate`, `gutenberg orchestrate`) as optional workflow aids, while preserving the "no automated worker spawning" language (V2 orchestration generates commands, not automatic execution). This update goes in Task 12.5 (new task below).

3. `test_manifest.py:test_chunk_entries` checks manifest chunk fields — new additive fields won't break this assertion but the test could be extended to verify new fields are present in V2.

## Implementation Constraints

- **Python stdlib only.** No external dependencies.
- **V1 behavior preserved.** Existing `gutenberg ingest` produces backward-compatible output. New manifest fields are additive. V1 runs without `status.json` work with all new commands via inference.
- **Schema version stays `"1.0"`.** All changes are additive and optional. V1 manifests without new fields remain valid with V2 tools. No need for a version bump.
- **Read-only validation.** `gutenberg validate` never modifies the run directory.
- **Dry-run default.** `gutenberg orchestrate` defaults to showing what would happen.
- **No agent API calls.** Orchestration generates commands/scripts for humans.
- **Deterministic output.** Same input → same output (except timestamps).
- **Version bump.** Update to `"0.2.0"` in **both** `src/gutenberg/__init__.py` and `pyproject.toml` at the start of V2 implementation (Phase 0, before any functional changes). The test `test_tool_info` in `test_manifest.py` asserts the version string — update the assertion too.

## Open Questions (Resolved During Planning)

1. **Where does neighbor context live — `chunk_text()` or separate function?**
   → In `chunk_text()`, consistent with existing `heading_context` enrichment. Add `context_chars` parameter.

2. **Per-chunk SHA-256 in manifest — when to add?**
   → Phase 11 (spec 08 motivation), but could be pulled into Phase 9. Placing in 11 keeps phases focused. The hash is of the **full chunk file on disk** (frontmatter + title + body) — see question 5.

3. **`missing` vs `pending` semantics?**
   → `pending` = initial state, never attempted. `missing` = checked filesystem, expected result not found. `infer_status` uses `done`/`pending` only (result exists or not). `missing` is set by validation or explicit check, not by initial creation.

4. **Worker command format in orchestration?**
   → Generic textual instruction: "Run worker prompt on chunk file, save result to results path." Include file paths. Don't assume a specific agent CLI.

5. **Per-chunk SHA-256 — hash of what exactly?**
   → Hash of the **full chunk file on disk** (YAML frontmatter + title line + body text), not just `ChunkInfo.text`. This is because spec 08 aims to detect corruption or edits to the file as written. The hash is computed from the constructed content string in `_run_ingest()` *before* writing (hash the string, then write it — avoids re-reading), then passed to `build_manifest()` via `chunk_hashes` dict.

6. **`context_chars` in manifest settings?**
   → Yes. Record in `settings` alongside `chunk_size` and `overlap` for reproducibility. Add `context_chars` parameter to `build_manifest()`.

7. **Orchestrator prompt updates for V2?**
   → Add a "V2 CLI Tools" section referencing `status`, `validate`, `orchestrate`. Keep "no automated worker spawning" language. This is Task 12.5, done last after all CLI commands exist.

---

## Code-Level Verification Findings (2026-04-24)

Findings from line-by-line V1 source and test review that inform V2 implementation:

### 1. `chunk_text()` single-chunk early return (chunking.py:107–117)

The early return creates a `ChunkInfo` without going through the main while-loop. Post-processing (position metadata, neighbor context, section detection) must apply to ALL chunks. Options: remove the early return (cleanest — the main loop handles single-chunk correctly), or duplicate post-processing. **Decision:** Remove early return in Task 9.2.

### 2. `build_manifest()` ordering dependency (manifest.py + cli.py)

In `_run_ingest()`, `build_manifest()` is called AFTER writing chunk files but BEFORE writing prompts (line ordering: chunk write → build_manifest → write_manifest → write_prompts). For Task 11.2 (per-chunk SHA-256), chunk file content strings must be collected during the chunk write loop, then passed to `build_manifest()`. This is natural — collect `chunk_hashes` dict in the loop, pass as kwarg.

### 3. Manifest chunk entry structure (manifest.py:53–62)

The chunk list comprehension in `build_manifest()` needs to grow for V2. Current fields: `id`, `path`, `char_start`, `char_end`, `estimated_tokens`, `heading_context`. Phase 9 adds 5–6 fields, Phase 11 adds `sha256`. The comprehension will get long — consider extracting a `_build_chunk_entry()` helper for readability, but this is optional.

### 4. Prompt generators are stateless (prompts.py)

All three `generate_*_prompt()` functions take `manifest` + `run_dir_name` and return strings. They access chunk data via `manifest["chunks"]`. V2 enriched fields (chunk_number, total_chunks, prev_context, next_context) will be available in the manifest dict by the time prompts are generated. No structural change needed — just template text updates.

### 5. `validate_manifest()` lenient design (manifest.py:80–133)

The existing `validate_manifest()` checks required top-level fields, source file, chunk files, and prompt files. It does NOT check:
- Chunk field types/values (no type checking on `char_start`, `estimated_tokens`, etc.)
- Chunk ordering strictness (the overlap check at line 121–125 is a no-op `pass`)
- Results directory contents

This lenience is intentional for V1. `validation.py` (Phase 11) builds a more thorough validation layer on top. The existing `validate_manifest()` can be called as-is by `validate_run()` as the "manifest structure" check.

### 6. Test fixture coverage (conftest.py)

Existing fixtures: `short_text`, `medium_text`, `heading_text`, `no_heading_text`, `unicode_text`, `source_file`. For V2 tests, need:
- A text with chapter markers (e.g., "CHAPTER I\n\nContent...CHAPTER II\n\nContent...") for section detection.
- A multi-chunk text at reasonable size (current `medium_text` is ~10k chars, single chunk at defaults; tests use `chunk_size=500` to force splits).
- These can be defined in individual test files or added to conftest.

### 7. `_run_ingest()` chunk frontmatter construction (cli.py:75–84)

The frontmatter is built as a plain f-string. V2 adds `chunk_index`, `chunk_number`, `total_chunks`, `prev_context`, `next_context`, and optionally `inferred_section`. The f-string approach works but needs careful YAML quoting for `prev_context`/`next_context` (arbitrary text). `json.dumps()` for those two values is the planned solution.

### 8. `paths.py` is a flat namespace

All path helpers are module-level functions. Adding `STATUS_FILENAME` and `status_path()` (Task 10.2) fits naturally. No structural concerns.

### 9. Test assertion patterns

- `test_chunk_entries` (test_manifest.py:72–79) iterates `zip(manifest["chunks"], chunks)` and checks `id`, `char_start`, `char_end`, `estimated_tokens`. New fields are additive — this test won't break but should be extended in Phase 9 to verify new fields.
- `test_no_automation_claims` (test_prompts.py:29–31) uses `"automated" not in prompt.lower() or "no automated" in prompt.lower()`. The V2 orchestrator prompt must contain "no automated" to pass. Current text: "There is no automated worker spawning in V1." → change to "There is no automated worker spawning." in Phase 12.
- `test_basic_ingest` (test_cli.py) checks for directory/file existence. Phase 10 adds `status.json` — this test doesn't break (it doesn't assert exhaustive file list), but we should extend it to verify `status.json` exists.

### 10. No `src/lib/` directory

The repo has no `src/lib/` directory. All shared code lives in `src/gutenberg/`. This is the project's standard library layout. New modules (`status.py`, `validation.py`, `orchestration.py`) go in `src/gutenberg/`.
