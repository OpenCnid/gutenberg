# Gutenberg Status

## Current State

V1 implementation complete and dogfooded. V2 implementation complete and validated. The next workstream is **V3 specification writing** for safe executable recursive orchestration; V3 has not been implemented yet.

## What's Built

- Boundary-aware chunking engine (heading/paragraph/sentence/whitespace/hard hierarchy)
- CLI: `python -m gutenberg ingest` with full option parsing
- Manifest builder + validator (`manifest.json`)
- Run-specific prompt generators (orchestrator, worker, synthesis)
- Chunk context enrichment: position metadata, neighboring context, conservative prose section detection
- `status.json` tracking plus `gutenberg status`
- Run integrity checks via `gutenberg validate`
- Orchestration planning via `gutenberg orchestrate`
- Dry-run planning, JSON output, script generation, resume/skip completed chunks, and synthesis readiness checks
- Python stdlib only, no external dependencies
- Test suite: 166 tests passing as of V2 validation

## V1 Dogfood Results (2026-04-24)

- Source: Frankenstein by Mary Shelley, 419k chars
- 9 chunks at default 50k/2k settings, <1s ingestion
- 3 workers (chunks 1, 5, 9) produced correct 7-section analyses
- Synthesis handled 6 missing chunks explicitly, 19k chars output
- Pattern validated: decompose → analyze snippets → synthesize

## V2 Dogfood Results (2026-04-24)

- Source: Frankenstein; or, the Modern Prometheus, Project Gutenberg #84
- Author: Mary Shelley
- Character count: 419,240
- Chunk count: 9 at default 50k/2k settings
- Verified: `status`, `validate`, context metadata, `orchestrate`, JSON plan output, script output, resume/skip completed chunks, and synthesis readiness checks
- Failure-mode checks passed: missing chunk, edited chunk/hash mismatch, empty result handling, missing `status.json` inference
- Bug found: stale `status.json` could disagree with filesystem after workers wrote result files manually
- Fix committed: `20eeea9 fix: reconcile status.json with filesystem on every read`
- Related fix: `bc86c69 fix: sentinel values for first/last chunk neighbor context`
- V2 orchestration baseline: `f2abb05 feat: automated orchestration — gutenberg orchestrate CLI + plan/script generation (spec 10)`
- Revised verdict: **V2 validated — ready for V3 specs**

## V3 Direction

V3 should move from orchestration planning to safe executable orchestration while preserving the artifact-first contract:

- Explicit execution only (`--execute` or equivalent), never hidden external agent calls
- Bounded worker concurrency with resumable lifecycle tracking
- Per-chunk task materialization so worker tasks are copy/executable without manual placeholder substitution
- Actual synthesis execution with explicit partial-synthesis behavior
- Auditable run artifacts, logs, and final reporting

## Decisions Locked

- Python standalone CLI
- Python stdlib first; justify any dependency before adding it
- Default chunk size: 50,000 chars
- Default overlap: 2,000 chars
- Boundary-aware chunking
- JSON manifest/status/artifacts for machines; markdown prompts/tasks/results for agents and humans
- V1/V2 compatibility; manifest schema changes should be additive whenever possible
- Dry-run/manual/script pathways remain available even after executable orchestration exists
