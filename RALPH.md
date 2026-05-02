# RALPH.md

Loop-specific operational rules for Ralph. Keep this file brief and practical because the loop may load it every iteration.

## Build & Run

Gutenberg is a standalone Python CLI project for ingesting long texts into Ralph/OpenClaw-friendly synthesis runs.

V1 and V2 are complete and validated (166 tests). V3 target:

- Python package under `src/gutenberg/`.
- CLI ingests one local text/markdown file into a run directory.
- JSON manifest for machines; markdown chunks/prompts/results for agents and humans.
- Default chunk size: `50_000` characters.
- Default overlap: `2_000` characters.
- Chunk on headings/paragraphs/sentences/whitespace before hard cuts.
- V1/V2 capabilities preserved: ingest, chunking, manifest, prompt generation, manual orchestration, status tracking, validation, orchestration planning.
- V3 adds: per-chunk task materialization, worker lifecycle/retry/resume, executor/worker launch, synthesis execution, and auditable run artifacts/reporting.
- New/extended CLI commands: `gutenberg execute`, `gutenberg synthesize`, `gutenberg report`, `gutenberg mark`/`retry`/`skip`.
- V3 execution requires explicit `--execute` flag — dry-run is always the default.
- Python stdlib only. No external dependencies.

## Validation

Run from repo root with the venv active:

```bash
source .venv/bin/activate
python -m pytest -v
```

Package is installed editable (`pip install -e .`). pytest is in the venv.

- Tests: `python -m pytest` (368 tests)
- Typecheck: not configured yet
- Lint: not configured yet

## Model Routing

- **Claude Opus-4-6 via lil-dario = broad orchestration / parallel fronts**
  Use the OpenClaw gateway-native Claude lane on `lil-dario/claude-opus-4-6` when running this skill. The old Sable hop and raw `claude` shell auth are both deprecated here. The bundled `loop.sh` provisions or reuses a dedicated OpenClaw agent for the current repo/model, verifies that the agent workspace/model match expectations, then runs each iteration in a fresh explicit session so Ralph keeps disk-based shared state without carrying chat context forward. This lane calls `openclaw gateway call agent` directly, not `openclaw agent`, because `openclaw agent` can fall back to embedded/local execution on gateway errors and that breaks strict auth-path guarantees. Default native settings are `RALPH_THINKING=high` and `RALPH_TIMEOUT=1800`. This is the best lane for broad orchestration, aggressive parallel delegation, and filling in holes, gaps, and assumptions when the work is not fully specified.
- **Codex gpt-5.5 xhigh = precise end-to-end execution on well-specified slices**
  Use Codex `gpt-5.5` in xhigh thinking mode. This lane is a direct Codex CLI lane, not an OpenClaw gateway-agent lane. Default to `codex exec --yolo` when using Codex through the outer Ralph sandbox. The bundled `loop.sh` applies the Codex xhigh override automatically when `RALPH_CLI=codex`. This is the best lane for goal-oriented execution with thorough research before action when the task is tightly scoped, clearly explained, and easy to pinpoint. It should study codebase patterns first, then complete the slice end-to-end without premature stopping. It is also excellent for architecture decisions, code review, debugging, and deep analysis.
- **Selection rule**
  Use Claude Opus-4-6 via lil-dario through OpenClaw as the broad orchestration lane and Codex `gpt-5.5` xhigh as the focused execution/review lane together for most real work. If forced to choose only one, favor Claude for ambiguous, cross-cutting, under-specified work or many parallel fronts; favor Codex for bounded, precise, already well-specified slices.
- Canonical per-model CLI and lane notes live in `references/methodology.md`, under `## CLI and Model Reference`.

## Lane Architecture

- **Claude lane:** OpenClaw Gateway-native. Dedicated per-repo agent, explicit session per iteration, strict gateway path, no raw `claude` fallback.
- **Codex lane:** direct Codex CLI via `codex exec --yolo`, under the same outer Ralph sandbox.
- Treat artifacts, git state, and test output as the source of truth for both lanes. Agent transcript history is a debugging aid, not the system of record.

## Self-Heal Configuration

self-heal-version: 1.1
retry-budget: 3
cost-ceiling: $2.00
global-catalog-path: ../../harness/failures/index.json

### Context Hooks

Shell commands executed on failure to capture diagnostic context.
Each hook should output to a file. Output is bundled into the diagnostic context.
Leave empty for default context only (error output + git diff).

### Severity Overrides

Force specific error patterns to a tier regardless of diagnosis.
Format: error-substring: tier

## Operational Notes

- `loop.sh` records per-iteration artifacts under `.ralph/artifacts/iterations/`, including metadata, repo state before/after, and for the Claude lane the exact gateway request/response JSON plus a response summary.
- If direct cross-agent history is disabled, prefer these artifacts plus git/log output when reviewing a prior Ralph iteration.
- If you enable cross-agent history in OpenClaw later, do it intentionally for debugging and failure forensics. Keep artifacts, git state, and test output as the primary verification record.
- Keep `IMPLEMENTATION_PLAN.md` focused on current loop state; durable requirements belong in `specs/`.

### Codebase Patterns

- Prefer standard-library Python unless a dependency is clearly justified.
- Keep chunking, manifest creation, prompt generation, and CLI parsing as separate units so tests can target them directly.
- Do not implement OpenClaw automation in V1; generate prompts and directories for manual orchestration only.
