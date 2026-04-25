# Gutenberg

Gutenberg is a standalone Python ingestion pipeline for turning long texts into Ralph/OpenClaw-friendly knowledge synthesis runs.

V1 keeps the integration deliberately manual: the CLI creates a machine-readable JSON manifest, markdown chunks, and markdown prompt templates. OpenClaw then loads the prompts and a human/operator spawns sub-agents by hand to prove the synthesis pattern before automating orchestration.

## V1 Decisions

- **Language:** Python
- **Project location:** `projects/gutenberg/`
- **Default chunk size:** `50_000` characters
- **Default overlap:** `2_000` characters
- **Chunking strategy:** prefer paragraph/heading boundaries; avoid hard cuts except as a last resort
- **Result format:** JSON manifest for machines; markdown everywhere else for agents and humans
- **V1 scope:** ingestion CLI, manifest schema, prompt templates, manual orchestration workflow

## Source of Truth

- Requirements live in `specs/`.
- Ralph operational rules live in `RALPH.md`.
- Current loop state lives in `IMPLEMENTATION_PLAN.md` once planning starts.
