# Gutenberg Status

## Current State

Ralph project scaffolded and V1 specs written.

## Decisions Locked

- Python standalone ingestion CLI.
- Project root: `projects/gutenberg/`.
- Default chunk size: `50_000` chars.
- Default overlap: `2_000` chars.
- Boundary-aware chunking prefers headings/paragraphs before hard cuts.
- Result format: `manifest.json` for machines; markdown chunks/prompts/results for agents and humans.
- V1 scope: ingestion CLI, manifest schema, prompt templates, manual orchestration proof.

## Next Step

Run Ralph planning mode from this directory:

```bash
./loop.sh plan
```
