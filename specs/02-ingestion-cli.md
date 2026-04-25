# Ingestion CLI

The ingestion CLI is the main V1 product. It accepts a local text/markdown source file and writes a self-contained run directory containing the source copy, chunk files, prompt files, and `manifest.json`.

## Command Shape

The exact executable name may be chosen during implementation, but the user-facing flow should feel like:

```bash
python -m gutenberg ingest path/to/source.txt --out runs/my-book
```

Required behavior:

- Accept one source file path.
- Accept an output/run directory path.
- Create the output directory if it does not exist.
- Refuse to overwrite a non-empty run directory unless an explicit force option exists.
- Copy or normalize the source into the run directory as `source.txt`.
- Generate chunks under `chunks/`.
- Generate prompts under `prompts/`.
- Generate `manifest.json` at the run root.

## Options

V1 should support:

- `--chunk-size <chars>`: default `50000`.
- `--overlap <chars>`: default `2000`.
- `--title <text>`: optional human title override.
- `--author <text>`: optional author metadata.
- `--force`: optional overwrite/recreate behavior if implementation chooses to support it.

Option validation:

- `--chunk-size` must be positive.
- `--overlap` must be zero or positive.
- `--overlap` must be smaller than `--chunk-size`.
- The CLI should fail clearly if the source file does not exist or is not readable.

## Output Directory

The generated directory should follow this shape:

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

The CLI should create `results/` even though workers fill it manually in V1.

## User Experience

- The CLI should print a short summary after success: run path, number of chunks, manifest path, and next manual step.
- Error messages should tell the operator what to fix.
- The tool should not require network access.
- The tool should not depend on OpenClaw being available at ingestion time.

## Acceptance Criteria

- Running the CLI on a sample source creates the expected directory tree.
- The default `--chunk-size` is `50000` characters.
- The default `--overlap` is `2000` characters.
- The CLI can override chunk size and overlap from flags.
- Invalid option combinations fail before writing partial run output when practical.
- Re-running into an existing non-empty directory is safe and does not silently destroy data.
- Success output gives the operator enough information to start the manual orchestration workflow.
