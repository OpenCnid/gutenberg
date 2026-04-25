# Gutenberg Status

## Current State

V1 implementation complete. All 57 tests passing. All 6 specs satisfied.

## What's Built

- Boundary-aware chunking engine (heading/paragraph/sentence/whitespace/hard hierarchy)
- CLI: `python -m gutenberg ingest` with full option parsing
- Manifest builder + validator (`manifest.json`)
- Run-specific prompt generators (orchestrator, worker, synthesis)
- Comprehensive test suite (57 tests across 4 test files)
- Python stdlib only, no external dependencies

## Decisions Locked

- Python standalone ingestion CLI
- Default chunk size: 50,000 chars
- Default overlap: 2,000 chars
- Boundary-aware chunking
- JSON manifest for machines; markdown for agents and humans
- Manual orchestration in V1 — no automated sub-agent spawning
