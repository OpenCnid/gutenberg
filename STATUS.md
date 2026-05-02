# Gutenberg Status

## Current State

V1–V3 complete. V3 dogfood-validated on Frankenstein (419K chars, 9 chunks, Sonnet 4.6 workers). 368 tests passing. Tagged 0.9.0.

## What's Built

### V1 (Specs 01–06)
- Boundary-aware chunking engine (heading/paragraph/sentence/whitespace/hard hierarchy)
- CLI: `python -m gutenberg ingest` with full option parsing
- Manifest builder + validator (`manifest.json`)
- Run-specific prompt generators (orchestrator, worker, synthesis)

### V2 (Specs 07–10)
- Chunk context enrichment: position metadata, neighboring context, section detection
- `status.json` tracking + `gutenberg status`
- Run integrity checks via `gutenberg validate`
- Orchestration planning via `gutenberg orchestrate` (dry-run, JSON, script output)
- Resume/skip completed chunks, synthesis readiness checks

### V3 (Specs 11–15)
- Per-chunk task materialization: `gutenberg tasks` (concrete task files, no placeholders)
- Worker lifecycle: `gutenberg mark`, `retry`, `skip` (durable states, attempt tracking, retry bounds)
- Executor/worker launch: `gutenberg execute` (command executor, bounded concurrency, signal handling)
- Synthesis execution: `gutenberg synthesize --execute` (partial synthesis support)
- Run artifacts & reporting: `gutenberg report` (event logs, per-attempt logs, orchestration.json)
- 14-check validation suite covering all V3 artifacts

### Design Invariants
- Python stdlib only, no external dependencies
- JSON for machines, markdown for agents and humans
- V1/V2 backward compatibility preserved
- Dry-run default; `--execute` required for any external launch

## V3 Dogfood Results (2026-05-02)

- Source: Frankenstein; or, the Modern Prometheus by Mary Shelley
- 419,240 characters, 9 chunks at default 50k/2k
- Model: Claude Sonnet 4.6 via lil-dario proxy
- Wall clock: ~15 minutes (sequential workers + synthesis)
- All 9 workers produced correct 7-section analyses (6–10KB each)
- Synthesis: 30KB unified analysis with 9 themes, cross-chunk quotes, methodology notes
- 14/14 validation checks pass
- 10 total attempts (1 retry for chunk-0001 from initial executor bug)
- Full audit trail: events.jsonl (23 events), per-attempt logs, orchestration.json
- Verdict: **V3 validated — pipeline works end-to-end with real LLM**

### Bugs Found in Dogfood
1. Synthesis LLM hallucinated tool calls in preamble (prompt issue, not logic)
2. Synthesis task shows `[missing]` until manual `tasks --refresh` after workers complete

### Friction Points
- No built-in LLM executor — required a wrapper script
- Worker tasks don't include chunk content (executor must assemble prompt)
- Workers and synthesis need separate executor configs

## Next Steps

- [ ] Fix BUG-2: auto-refresh synthesis task in `synthesize --execute`
- [ ] Add result format validation (check output starts with expected markdown structure)
- [ ] First-class LLM executor type (API calls, prompt assembly, response extraction built in)
- [ ] Consider concurrent execution with rate limiting for larger texts
