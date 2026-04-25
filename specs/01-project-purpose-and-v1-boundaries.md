# Project Purpose and V1 Boundaries

Gutenberg helps OpenClaw/Ralph perform knowledge synthesis over long texts that do not fit comfortably in one model context.

The tool ingests a source text, splits it into readable markdown chunks, writes a canonical machine-readable manifest, and emits prompt templates that guide a human/operator through manual orchestration with sub-agents.

## Jobs To Be Done

- As an operator, I want to turn one long text file into a reproducible synthesis workspace so I can delegate chunk analysis safely.
- As an operator, I want chunks and prompts to be human-readable markdown so I can inspect, debug, and adjust a run without special tooling.
- As an automation author, I want one JSON manifest to describe the run so later OpenClaw integration can rely on a stable machine contract.
- As a Ralph loop, I want tight v1 boundaries so I can implement the ingestion foundation before automating orchestration.

## V1 Scope

V1 includes:

- A Python ingestion CLI.
- A run directory layout.
- A canonical `manifest.json` schema.
- Markdown chunk files with lightweight metadata.
- Markdown prompt templates for orchestrator, worker, and synthesis roles.
- Manual instructions for running the pattern by hand in OpenClaw/Ralph.
- Basic automated validation for deterministic filesystem output and schema shape.

V1 does not include:

- Automatic OpenClaw session spawning.
- Automatic parallel worker scheduling.
- Provider/model abstraction beyond prompt text.
- Database storage.
- Web UI.
- Multi-book corpus management.
- Semantic deduplication or embeddings.
- Perfect token counting.

## Design Invariants

- JSON is for machines; markdown is for agents and humans.
- The manifest is the canonical contract for run metadata and file paths.
- Markdown files should remain pleasant to read directly in a terminal or editor.
- The CLI should be deterministic for the same input and options, except for explicit timestamp/run id fields.
- A failed run should leave enough files/logging for a human to understand what happened.
- Avoid premature automation; prove the manual orchestration pattern first.

## Acceptance Criteria

- A new contributor can read this spec set and understand what V1 should and should not build.
- Ralph planning produces tasks that focus on ingestion, schema, prompts, and manual workflow instead of full automation.
- The repo has clear docs explaining the decisions: Python, `projects/gutenberg/`, `50_000` char chunks, `2_000` char overlap, boundary-aware chunking, and hybrid JSON/markdown results.
