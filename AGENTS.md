# AGENTS.md

This file is the short map, not the Ralph runbook.

If you are entering this repository cold, start here, then progressively disclose deeper docs as needed.

## Start Here

1. `README.md` if present, for project overview and navigation
2. `ARCHITECTURE.md` if present, for repo codemap and boundaries
3. `docs/index.md` if present, for the full knowledge base map
4. `PLANS.md` if present, for long-running implementation-plan rules
5. `RALPH.md` for Ralph-specific build, validation, model-routing, and self-heal rules
6. `IMPLEMENTATION_PLAN.md` for the current loop state
7. `specs/*` for source-of-truth requirements

## Repo Doc Philosophy

- `AGENTS.md` stays short and stable.
- Durable knowledge lives in focused docs, not here.
- `RALPH.md` holds Ralph-specific operational guidance.
- `IMPLEMENTATION_PLAN.md` is shared loop state, not durable documentation.
- When you learn something important, update the real source-of-truth doc, not just the current chat.

## Root Files

- `AGENTS.md` — this file, the quick entry map
- `RALPH.md` — Ralph operational guide and self-heal config
- `IMPLEMENTATION_PLAN.md` — current loop state and discoveries
- `PROMPT_plan.md` / `PROMPT_build.md` — loop prompts
- `specs/` — requirements by topic (6 specs)

## Source Layout

- `src/gutenberg/` — Python package
  - `cli.py` — CLI entry (ingest, status, validate, orchestrate, tasks, execute, synthesize, report, mark, retry, skip)
  - `chunking.py` — boundary-aware text splitter
  - `manifest.py` — `manifest.json` builder and validator
  - `prompts.py` — orchestrator/worker/synthesis prompt generators
  - `paths.py` — run directory path helpers (V1/V2/V3)
  - `status.py` — per-chunk status tracking and reconciliation
  - `orchestration.py` — orchestration planning and script generation
  - `validation.py` — structural integrity and completeness checks
  - `tasks.py` — per-chunk task materialization (V3, spec 14)
  - `lifecycle.py` — worker lifecycle, retry, failure management (V3, spec 12)
  - `executor.py` — executor/worker launch integration (V3, spec 11)
  - `synthesis.py` — synthesis execution (V3, spec 13)
  - `reporting.py` — event logging, orchestration summary, reports (V3, spec 15)
- `tests/` — pytest suite (330 tests)
- `pyproject.toml` — package config

## Invariants

- Keep this file short.
- Prefer adding detail to focused docs or `RALPH.md`.
- Put build, test, lint, typecheck, model-routing, and self-heal rules in `RALPH.md`, not here.
- Keep `IMPLEMENTATION_PLAN.md` current if the loop is active.
- If a doc becomes large and mixed-purpose, split it by concern.

## If You Only Remember One Thing

`AGENTS.md` tells you where to look.
`RALPH.md` tells Ralph how to operate.
`specs/` and `IMPLEMENTATION_PLAN.md` tell Ralph what to do next.
