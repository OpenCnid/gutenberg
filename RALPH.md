# RALPH.md

Loop-specific operational rules for Ralph. Keep this file brief and practical because the loop may load it every iteration.

## Build & Run

Succinct rules for how to build and run the project.

## Validation

Run these after implementing to get immediate feedback:

- Tests: `[test command]`
- Typecheck: `[typecheck command]`
- Lint: `[lint command]`

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

Example (Playwright):
  screenshot: npx playwright screenshot --output /tmp/heal-screenshot.png
  game-state: node scripts/dump-game-state.js > /tmp/heal-gamestate.json

Example (API):
  health: curl -s $HEALTHCHECK_URL > /tmp/heal-api-state.json

### Severity Overrides

Force specific error patterns to a tier regardless of diagnosis.
Format: error-substring: tier

Example:
  "ECONNREFUSED": human
  "Cannot read properties of null": auto

## Operational Notes

Succinct learnings about how to run the project:

- `loop.sh` records per-iteration artifacts under `.ralph/artifacts/iterations/`, including metadata, repo state before/after, and for the Claude lane the exact gateway request/response JSON plus a response summary.
- If direct cross-agent history is disabled, prefer these artifacts plus git/log output when reviewing a prior Ralph iteration.
- If you enable cross-agent history in OpenClaw later, do it intentionally for debugging and failure forensics. Keep artifacts, git state, and test output as the primary verification record.

### Codebase Patterns

...
