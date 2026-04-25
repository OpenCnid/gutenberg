"""Generate run-specific prompt templates for manual orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gutenberg import paths as P


def generate_orchestrator_prompt(manifest: dict[str, Any], run_dir_name: str) -> str:
    """Generate the orchestrator prompt for a specific run."""
    chunks = manifest.get("chunks", [])
    chunk_count = len(chunks)
    chunk_list = "\n".join(f"- `{c['path']}` ({c['id']})" for c in chunks)
    title = manifest.get("source", {}).get("title", "") or "Untitled"

    return f"""# Orchestrator Prompt — {title}

## Overview

You are orchestrating a knowledge synthesis run over a long text that has been split into {chunk_count} chunks.

**Run directory:** `{run_dir_name}/`
**Manifest:** `{P.MANIFEST_FILENAME}`
**Source:** `{P.SOURCE_FILENAME}`

## Chunks

{chunk_list}

## Manual Orchestration Steps

This is a **manual orchestration workflow**. There is no automated worker spawning in V1.

### Step 1: Review the manifest

Study `{P.MANIFEST_FILENAME}` to understand the source, chunk count, and settings.

### Step 2: Assign workers

For each chunk, spawn or assign one worker (sub-agent or manual session). Give each worker:

1. The **worker prompt** from `{P.PROMPTS_DIR}/{P.WORKER_PROMPT}`
2. Exactly **one chunk file** from `{P.CHUNKS_DIR}/`

### Step 3: Collect results

Each worker should write their analysis to:

`{P.RESULTS_DIR}/{{chunk_id}}.analysis.md`

For example: `{P.RESULTS_DIR}/chunk-0001.analysis.md`

### Step 4: Track completion

Monitor which chunks have been analyzed. Missing or failed chunks should be noted before synthesis.

Expected result files:
{chr(10).join(f"- `{P.RESULTS_DIR}/{c['id']}.analysis.md`" for c in chunks)}

### Step 5: Run synthesis

Once all (or most) worker results are available, run the synthesis prompt from `{P.PROMPTS_DIR}/{P.SYNTHESIS_PROMPT}` over all results.

The final synthesis should be written to `{P.RESULTS_DIR}/synthesis.md`.

## Important Notes

- Each worker should analyze only their assigned chunk.
- Workers should not have access to other chunks to avoid cross-contamination.
- If a worker fails, re-run it on the same chunk rather than skipping.
- The synthesis step should explicitly note any missing chunk analyses.
"""


def generate_worker_prompt(manifest: dict[str, Any], run_dir_name: str) -> str:
    """Generate the worker prompt for a specific run."""
    title = manifest.get("source", {}).get("title", "") or "Untitled"

    return f"""# Worker Prompt — {title}

## Your Task

You are a worker analyzing **one chunk** of a longer text. You will be given a single chunk file to analyze.

## Instructions

1. Read the assigned chunk file carefully.
2. Analyze the content thoroughly.
3. Write your analysis in the structured format below.
4. Save your output to `{P.RESULTS_DIR}/{{chunk_id}}.analysis.md` (where `{{chunk_id}}` matches the chunk you were assigned, e.g., `chunk-0001`).

## Important Rules

- Analyze **only** the assigned chunk. Do not reference or assume content from other chunks.
- Preserve important quotes with enough surrounding context to be meaningful.
- Clearly distinguish between **source claims** (what the text says) and **your interpretation** (what you think it means).
- When uncertain, note the uncertainty rather than inventing cross-chunk context.
- If you do not have file write access, return the analysis in the format below for a human to save.

## Required Output Format

Write your analysis as structured markdown with these sections:

```markdown
# Chunk Summary

A concise summary of the main content and arguments in this chunk.

# Key Claims / Ideas

- Claim or idea 1
- Claim or idea 2
- ...

# Important Quotes

> "Quote 1" (with enough context to be meaningful)

> "Quote 2"

# Entities / Concepts

- Entity or concept 1: brief description
- Entity or concept 2: brief description

# Open Questions

- Question raised by this chunk that may be answered elsewhere
- Ambiguity or gap in the source material

# Connections To Other Chunks

- Potential connection 1 (note: you may not have seen other chunks — flag potential links based on references, names, or themes mentioned)

# Synthesis Notes

Any observations that would help a synthesizer combine this analysis with others. Note themes, recurring patterns, or structural elements.
```
"""


def generate_synthesis_prompt(manifest: dict[str, Any], run_dir_name: str) -> str:
    """Generate the synthesis prompt for a specific run."""
    chunks = manifest.get("chunks", [])
    chunk_count = len(chunks)
    title = manifest.get("source", {}).get("title", "") or "Untitled"

    result_files = "\n".join(
        f"- `{P.RESULTS_DIR}/{c['id']}.analysis.md`" for c in chunks
    )

    return f"""# Synthesis Prompt — {title}

## Your Task

You are the synthesizer for a knowledge synthesis run. {chunk_count} chunks of a long text were analyzed by individual workers. Your job is to produce a coherent whole-text synthesis from their analyses.

## Inputs

**Manifest:** `{P.MANIFEST_FILENAME}`

**Expected worker result files:**
{result_files}

## Instructions

### Step 1: Check for missing analyses

Before synthesizing, verify which chunk analysis files are present. List any missing chunks explicitly — do not silently ignore gaps.

### Step 2: Read all available analyses

Study every available `{P.RESULTS_DIR}/*.analysis.md` file.

### Step 3: Synthesize

Produce a coherent synthesis that:

- Integrates key claims and ideas across all chunks.
- Preserves important disagreements, ambiguities, and open questions.
- Identifies themes and patterns that span multiple chunks.
- Includes a compact list of the strongest quotes/evidence from across the text.
- Notes where chunk boundaries may have affected analysis (e.g., ideas split across chunks).

### Step 4: Write output

Save your synthesis to `{P.RESULTS_DIR}/synthesis.md`.

## Output Format

Write your synthesis as structured markdown:

```markdown
# Synthesis — {title}

## Missing Chunks

List any chunk analyses that were not available.

## Executive Summary

A concise overview of the entire text's main arguments and contributions.

## Key Themes

### Theme 1
Description and supporting evidence from multiple chunks.

### Theme 2
...

## Critical Analysis

Strengths, weaknesses, gaps, and contradictions in the source material.

## Key Quotes

The most important quotes from across the text, with chunk references.

## Open Questions

Unresolved questions, ambiguities, or areas requiring further investigation.

## Methodology Notes

Any observations about how the chunking or analysis process may have affected the synthesis.
```
"""


def write_prompts(manifest: dict[str, Any], run_dir: Path) -> None:
    """Write all three prompt files to the run directory."""
    run_dir_name = run_dir.name

    prompts_path = P.prompts_dir(run_dir)
    prompts_path.mkdir(parents=True, exist_ok=True)

    orchestrator = generate_orchestrator_prompt(manifest, run_dir_name)
    P.orchestrator_prompt_path(run_dir).write_text(orchestrator, encoding="utf-8")

    worker = generate_worker_prompt(manifest, run_dir_name)
    P.worker_prompt_path(run_dir).write_text(worker, encoding="utf-8")

    synthesis = generate_synthesis_prompt(manifest, run_dir_name)
    P.synthesis_prompt_path(run_dir).write_text(synthesis, encoding="utf-8")
