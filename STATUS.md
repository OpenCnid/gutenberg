# Gutenberg Status

## Current State

V1 implementation complete. Dogfood pass complete on Frankenstein (419k chars).

## What's Built

- Boundary-aware chunking engine (heading/paragraph/sentence/whitespace/hard hierarchy)
- CLI: `python -m gutenberg ingest` with full option parsing
- Manifest builder + validator (`manifest.json`)
- Run-specific prompt generators (orchestrator, worker, synthesis)
- Comprehensive test suite (57 tests across 4 test files)
- Python stdlib only, no external dependencies

## V1 Dogfood Results (2026-04-24)

- Source: Frankenstein by Mary Shelley, 419k chars
- 9 chunks at default 50k/2k settings, <1s ingestion
- 3 workers (chunks 1, 5, 9) produced correct 7-section analyses
- Synthesis handled 6 missing chunks explicitly, 19k chars output
- Pattern validated: decompose → analyze snippets → synthesize

## V2 Friction Points (from dogfood)

1. No heading context for plain prose (no markdown headings = empty context)
2. Manual orchestration is tedious at scale (3 workers = 3 manual spawns)
3. No completion tracking (must check filesystem manually)
4. Worker prompt lacks chunk position (e.g., "chunk 5 of 9")
5. No `gutenberg validate <run>` CLI command
6. No resume capability

## Decisions Locked

- Python standalone ingestion CLI
- Default chunk size: 50,000 chars
- Default overlap: 2,000 chars
- Boundary-aware chunking
- JSON manifest for machines; markdown for agents and humans
- Manual orchestration in V1 — no automated sub-agent spawning
