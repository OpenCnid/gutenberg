# Manifest and Run Layout

`manifest.json` is the canonical machine-readable contract for a Gutenberg run. Markdown files are the canonical human/agent-readable artifacts.

## Run Layout

A complete V1 run directory should look like:

```text
<run>/
  manifest.json
  source.txt
  prompts/
    orchestrator.md
    worker.md
    synthesis.md
  chunks/
    chunk-0001.md
    chunk-0002.md
  results/
    .gitkeep
```

Later manual worker outputs should naturally fit as:

```text
results/
  chunk-0001.analysis.md
  chunk-0002.analysis.md
  synthesis.md
```

The CLI does not need to create worker analyses in V1.

## Manifest Fields

The manifest should be valid JSON with at least these fields:

```json
{
  "schema_version": "1.0",
  "tool": {
    "name": "gutenberg",
    "version": "0.1.0"
  },
  "created_at": "2026-04-24T00:00:00Z",
  "source": {
    "input_path": "...",
    "stored_path": "source.txt",
    "title": "...",
    "author": "...",
    "sha256": "...",
    "char_count": 123456
  },
  "settings": {
    "chunk_size": 50000,
    "overlap": 2000,
    "splitter": "boundary-aware-v1",
    "estimated_token_method": "chars_div_4"
  },
  "prompts": {
    "orchestrator": "prompts/orchestrator.md",
    "worker": "prompts/worker.md",
    "synthesis": "prompts/synthesis.md"
  },
  "chunks": [
    {
      "id": "chunk-0001",
      "path": "chunks/chunk-0001.md",
      "char_start": 0,
      "char_end": 50000,
      "estimated_tokens": 12500,
      "heading_context": []
    }
  ],
  "results": {
    "directory": "results",
    "expected_worker_pattern": "results/{chunk_id}.analysis.md",
    "expected_synthesis_path": "results/synthesis.md"
  }
}
```

Implementation may add fields, but should not omit the above without a good reason captured in docs.

## Path Rules

- Paths inside the manifest should be relative to the run directory unless explicitly marked as original/input paths.
- The original source path may be absolute or relative as provided by the user.
- Generated paths should use POSIX-style separators in JSON for portability.
- The manifest should not require reading markdown frontmatter to discover the run structure.

## Validation Expectations

The project should include a way to validate a generated manifest, either as a CLI command or test helper.

Validation should check:

- Required fields exist.
- Referenced files exist.
- Chunk paths are unique.
- Chunk ids are unique and ordered.
- Chunk offsets are numeric and monotonic.
- Settings reflect the CLI options used.

## Acceptance Criteria

- A generated run contains `manifest.json` plus markdown artifacts in the expected places.
- `manifest.json` can be loaded by standard Python JSON tooling.
- The manifest alone is enough for future automation to find source, prompts, chunks, and expected result paths.
- The manifest records source checksum and chunking settings for reproducibility.
- Manifest paths are stable and relative to the run directory.
