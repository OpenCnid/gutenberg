0a. Study @AGENTS.md to discover the repo map and decide which docs matter for this iteration.
0b. Study @RALPH.md to learn build, validation, model-routing, and self-heal constraints for this project.
0c. Study @STATUS.md and @IMPLEMENTATION_PLAN.md to understand the V1/V2 completion record and current V3 planning state.
0d. Study `specs/*`, especially specs 11–15, as the source of truth for the next implementation pass.
0e. Study `src/gutenberg/*` and `tests/*` to confirm current behavior before planning or implementing changes.

1. Plan only unless explicitly told to build. Do **not** assume functionality is missing; confirm with code and tests first. Use Codex `gpt-5.5` xhigh for precise codebase study and Claude Opus-4-6 via the OpenClaw native lane for broad orchestration/architecture review when useful. Keep @IMPLEMENTATION_PLAN.md current with decisions, dependencies, and completed/incomplete items.

IMPORTANT: V2 is complete and validated. Latest validation evidence: `python -m pytest -q` → 166 passed; dogfood on Frankenstein (Project Gutenberg #84, 419,240 chars, 9 chunks) passed status/validate/context/orchestrate/script/resume/synthesis-check and failure-mode tests; stale `status.json` reconciliation was fixed in `20eeea9`.

ULTIMATE GOAL: Plan Gutenberg V3 on top of the validated V2 baseline. V3 moves from orchestration planning to safe executable recursive orchestration while preserving the artifact-first contract. Target specs 11–15: executor/worker launch integration, worker lifecycle/retry/resume, synthesis execution, per-chunk task materialization, and auditable run artifacts/reporting. Preserve V1/V2 compatibility, Python stdlib-first implementation, deterministic file artifacts, dry-run/manual/script fallbacks, and explicit `--execute` safety. Do not silently launch external agents.
