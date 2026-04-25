# Gutenberg

Standalone Python ingestion CLI for long-text knowledge synthesis. Turns one large text/markdown file into a reproducible run directory with chunks, prompts, and a machine-readable manifest.

## Quick Start

```bash
cd projects/gutenberg
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest

# Ingest a source file
python -m gutenberg ingest path/to/source.txt --out runs/my-book

# Run tests
python -m pytest -v
```

## Usage

```bash
python -m gutenberg ingest SOURCE --out DIR [OPTIONS]

Options:
  --chunk-size N   Target chunk size in chars (default: 50000)
  --overlap N      Overlap between chunks in chars (default: 2000)
  --title TEXT     Human-readable title
  --author TEXT    Author metadata
  --force          Overwrite existing non-empty run directory
```

## Output

```
<run>/
  manifest.json          # Machine-readable run contract
  source.txt             # Copied source
  chunks/
    chunk-0001.md        # Boundary-aware chunks with YAML frontmatter
    chunk-0002.md
  prompts/
    orchestrator.md      # Manual orchestration workflow
    worker.md            # Worker analysis template
    synthesis.md         # Synthesis instructions
  results/
    .gitkeep             # Workers fill this manually in V1
```

## V1 Decisions

- **Python stdlib only** — no external dependencies
- **50,000 char default chunks** with 2,000 char overlap
- **Boundary-aware chunking** — prefers headings > paragraphs > sentences > whitespace > hard cuts
- **JSON manifest** for machines; **markdown** for agents and humans
- **Manual orchestration** — no automated sub-agent spawning in V1

## Source of Truth

- Requirements: `specs/`
- Ralph operational rules: `RALPH.md`
- Current state: `IMPLEMENTATION_PLAN.md`
