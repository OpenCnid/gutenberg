# Prompt Templates and Manual Orchestration

V1 proves the knowledge synthesis pattern manually before automating OpenClaw integration.

The ingestion CLI should generate markdown prompt templates that an operator can load into OpenClaw and use while spawning sub-agents by hand.

## Generated Prompt Files

Each run should include:

```text
prompts/
  orchestrator.md
  worker.md
  synthesis.md
```

The templates should be concrete enough to use immediately for the generated run, not generic placeholders that require heavy editing.

## Orchestrator Prompt

The orchestrator prompt should tell the main agent/operator to:

- Study `manifest.json`.
- Study the list of chunks.
- Spawn or assign one worker per chunk as appropriate.
- Give each worker the worker prompt and exactly one chunk file.
- Ask workers to write results in the expected `results/{chunk_id}.analysis.md` shape.
- After worker results exist, run the synthesis prompt over all worker outputs.
- Track missing or failed chunks explicitly.

The orchestrator prompt should not pretend V1 has automated worker spawning. It should describe manual steps honestly.

## Worker Prompt

The worker prompt should require structured markdown output, not strict JSON.

Required worker result sections:

```md
# Chunk Summary

# Key Claims / Ideas

# Important Quotes

# Entities / Concepts

# Open Questions

# Connections To Other Chunks

# Synthesis Notes
```

Worker instructions should emphasize:

- Analyze only the assigned chunk.
- Preserve important quotes with enough context.
- Distinguish source claims from worker interpretation.
- Note uncertainty instead of inventing cross-chunk context.
- Write the result to `results/{chunk_id}.analysis.md` when file access is available, or return the same markdown for a human to save.

## Synthesis Prompt

The synthesis prompt should tell the synthesizer to:

- Study `manifest.json`.
- Study every available `results/*.analysis.md` file.
- Identify missing chunks before synthesizing.
- Produce a coherent whole-text synthesis.
- Preserve important disagreements, ambiguities, and open questions.
- Include a compact list of the strongest quotes/evidence.

The synthesis output should be markdown, expected at `results/synthesis.md`.

## Why Markdown Results

V1 should intentionally prefer structured markdown for worker and synthesis results because:

- It is easier for agents to produce reliably than strict JSON.
- It is easier for humans to inspect and repair.
- Section headings still give synthesis enough structure.
- The JSON manifest already provides the machine contract.

## Acceptance Criteria

- The CLI generates all three prompt files for every run.
- Prompt files include the concrete run paths and chunk/result conventions.
- Worker output format is structured markdown with the required sections.
- The prompts clearly support manual OpenClaw sub-agent orchestration.
- The prompts avoid claiming automation that does not exist in V1.
