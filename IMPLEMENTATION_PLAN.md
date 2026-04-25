# Implementation Plan — Gutenberg V1

> **Status:** Planning complete. No implementation started.
> **Last updated:** 2026-04-24
> **Repo state:** Greenfield — `src/` is empty, no Python files, no packaging, no tests.

## Confirmed Missing

Everything. The `src/` directory is empty. No `pyproject.toml`, no tests directory, no Python code of any kind exists. All items below need to be built from scratch.

---

## Phase 1: Project Scaffolding

**Goal:** Establish a runnable Python package structure so all subsequent phases can import and test.

| # | Task | Spec | Status |
|---|------|------|--------|
| 1.1 | Create `pyproject.toml` with project metadata, version `0.1.0`, Python ≥3.10, no external deps, `[project.scripts]` entry for CLI | 06 | ☐ |
| 1.2 | Create `src/gutenberg/__init__.py` with `__version__ = "0.1.0"` | 06 | ☐ |
| 1.3 | Create `src/gutenberg/__main__.py` to support `python -m gutenberg` | 02 | ☐ |
| 1.4 | Create empty module stubs: `cli.py`, `chunking.py`, `manifest.py`, `prompts.py`, `paths.py` | 06 | ☐ |
| 1.5 | Create `tests/` directory with `conftest.py` (tmp_path fixtures, sample text helpers) | 06 | ☐ |
| 1.6 | Update `.gitignore` for Python artifacts (`__pycache__`, `*.egg-info`, `.pytest_cache`, etc.) | 06 | ☐ |
| 1.7 | Verify `python -m pytest` runs (even if 0 tests) and update `RALPH.md` validation section if needed | 06 | ☐ |

**Dependencies:** None.
**Lane:** Either — this is mechanical scaffolding.

---

## Phase 2: Core Chunking Engine (`chunking.py`)

**Goal:** Implement boundary-aware chunking with overlap. This is the hardest algorithmic piece and the foundation for everything else.

| # | Task | Spec | Status |
|---|------|------|--------|
| 2.1 | Implement boundary detection: find candidate split points by preference (heading → paragraph → sentence → whitespace → hard) | 03 | ☐ |
| 2.2 | Implement `chunk_text(text, chunk_size=50000, overlap=2000) -> list[ChunkInfo]` returning chunk metadata (id, char_start, char_end, text) | 03 | ☐ |
| 2.3 | Implement overlap: each chunk starts ~`overlap` chars before the previous chunk's end, snapped to a clean boundary | 03 | ☐ |
| 2.4 | Implement token estimation: `ceil(chars / 4)` as documented heuristic | 03 | ☐ |
| 2.5 | Implement chunk ID generation: zero-padded `chunk-0001`, `chunk-0002`, etc. | 03 | ☐ |
| 2.6 | Implement heading context tracking: record active heading stack at chunk start for manifest `heading_context` field | 04 | ☐ |
| 2.7 | Handle edge cases: single-chunk files, files smaller than chunk_size, no paragraph/heading boundaries, non-ASCII text, large overlap relative to chunk_size | 03 | ☐ |
| 2.8 | Ensure deterministic output for same input and options | 03 | ☐ |

**Dependencies:** Phase 1 (package structure exists).
**Lane:** Codex xhigh — tightly scoped, algorithmic, well-specified.

### Design Notes

- **Boundary preference algorithm:** Walk forward from target split point; search backward for best boundary within a tolerance window (e.g., last 20% of chunk_size). If no good boundary found in the backward window, accept the target position. This keeps chunks near the target size while preferring clean breaks.
- **Overlap boundary snapping:** When computing overlap start for chunk N+1, snap backward from `chunk_N_end - overlap` to the nearest clean boundary. This avoids splitting mid-word/sentence in the overlap region.
- **Data class:** Use a `@dataclass` for `ChunkInfo` with fields: `id`, `char_start`, `char_end`, `text`, `estimated_tokens`, `heading_context`.
- **Heading tracking:** Scan for markdown headings (`# ...` through `###### ...`) as the text is processed. Maintain a stack of active headings; record the stack at each chunk's start position.

---

## Phase 3: Chunk File Writer (`paths.py` + integration)

**Goal:** Write chunk markdown files with YAML frontmatter to the run directory.

| # | Task | Spec | Status |
|---|------|------|--------|
| 3.1 | Implement `paths.py` with run directory constants and path helpers (chunk path, prompt path, manifest path, results dir, source path) | 04 | ☐ |
| 3.2 | Implement chunk file writer: generate `chunks/chunk-NNNN.md` with YAML frontmatter (`chunk_id`, `source`, `char_start`, `char_end`, `estimated_tokens`) and body text | 03 | ☐ |
| 3.3 | Ensure frontmatter offsets match the manifest offsets (single source of truth from `ChunkInfo`) | 03, 04 | ☐ |

**Dependencies:** Phase 2 (chunking produces `ChunkInfo` objects).
**Lane:** Either — straightforward file I/O.

---

## Phase 4: Manifest Generation (`manifest.py`)

**Goal:** Build and write `manifest.json` with all required fields from spec 04.

| # | Task | Spec | Status |
|---|------|------|--------|
| 4.1 | Implement manifest dict builder: assembles the full manifest structure from source metadata, settings, chunk list, and prompt paths | 04 | ☐ |
| 4.2 | Compute source SHA-256 and character count | 04 | ☐ |
| 4.3 | Record all required fields: `schema_version`, `tool`, `created_at`, `source`, `settings`, `prompts`, `chunks`, `results` | 04 | ☐ |
| 4.4 | Write `manifest.json` with `json.dump` (indent=2, sorted keys for determinism) | 04 | ☐ |
| 4.5 | Implement manifest validator (test helper or standalone function): check required fields, file existence, chunk uniqueness/ordering, offset monotonicity | 04 | ☐ |

**Dependencies:** Phase 2 (chunk metadata), Phase 3 (path conventions).
**Lane:** Either — schema construction is well-specified.

---

## Phase 5: Prompt Templates (`prompts.py`)

**Goal:** Generate run-specific markdown prompt files for orchestrator, worker, and synthesis roles.

| # | Task | Spec | Status |
|---|------|------|--------|
| 5.1 | Implement orchestrator prompt generator: references manifest, chunk list, worker prompt, result paths, manual orchestration steps | 05 | ☐ |
| 5.2 | Implement worker prompt generator: includes required output sections (Chunk Summary, Key Claims, Important Quotes, Entities/Concepts, Open Questions, Connections, Synthesis Notes), references chunk file and result path pattern | 05 | ☐ |
| 5.3 | Implement synthesis prompt generator: references manifest, all result files, missing-chunk detection, synthesis output path | 05 | ☐ |
| 5.4 | All prompts must be concrete to the run (include actual paths, chunk counts, file names) — not generic templates | 05 | ☐ |
| 5.5 | Prompts must honestly describe manual orchestration — no claims of automation that doesn't exist | 05 | ☐ |

**Dependencies:** Phase 3 (path conventions), Phase 4 (manifest structure for referencing).
**Lane:** Claude Opus-4-6 — prompt quality benefits from broader judgment about what makes prompts actually useful for operators.

### Design Notes

- Prompts should embed the specific run's chunk count, directory name, and file listing so an operator can copy-paste them directly.
- Worker prompt should include the exact required sections as a template the worker fills in.
- Orchestrator prompt should give step-by-step manual instructions, not assume any automation.
- Synthesis prompt should instruct the synthesizer to check for missing chunk analyses before proceeding.

---

## Phase 6: CLI (`cli.py`)

**Goal:** Wire everything together behind `python -m gutenberg ingest`.

| # | Task | Spec | Status |
|---|------|------|--------|
| 6.1 | Implement argument parsing with `argparse`: `ingest` subcommand, positional `source`, `--out`, `--chunk-size`, `--overlap`, `--title`, `--author`, `--force` | 02 | ☐ |
| 6.2 | Implement option validation: positive chunk_size, non-negative overlap, overlap < chunk_size, source file exists and is readable | 02 | ☐ |
| 6.3 | Implement run directory creation: create output dir, refuse non-empty dir unless `--force`, create subdirs (`chunks/`, `prompts/`, `results/`) | 02 | ☐ |
| 6.4 | Copy/normalize source file to `source.txt` in run directory | 02 | ☐ |
| 6.5 | Orchestrate pipeline: read source → chunk → write chunks → build manifest → write manifest → generate prompts → write prompts → create `results/.gitkeep` | 02 | ☐ |
| 6.6 | Print success summary: run path, chunk count, manifest path, next manual step | 02 | ☐ |
| 6.7 | Implement error handling: clear messages for missing source, invalid options, I/O failures | 02 | ☐ |
| 6.8 | Wire `__main__.py` to call CLI entry point | 02 | ☐ |

**Dependencies:** Phases 2–5 (all core modules).
**Lane:** Either — integration wiring.

---

## Phase 7: Tests

**Goal:** Cover all acceptance criteria from specs with automated tests using pytest.

| # | Task | Spec | Status |
|---|------|------|--------|
| 7.1 | Test scaffolding: `conftest.py` with fixtures for sample texts (short, medium, large, heading-rich, no-headings, non-ASCII) and tmp_path helpers | 06 | ☐ |
| 7.2 | Chunking unit tests: default sizes, custom sizes, boundary preference verification, overlap correctness, single-chunk files, edge cases | 03 | ☐ |
| 7.3 | Chunking coverage test: verify reconstructing chunks (minus overlap) covers the full source without gaps | 03 | ☐ |
| 7.4 | Manifest tests: required fields present, paths exist, chunk IDs unique and ordered, offsets monotonic, settings match CLI options | 04 | ☐ |
| 7.5 | Manifest validation tests: validator catches missing fields, missing files, duplicate IDs | 04 | ☐ |
| 7.6 | Prompt tests: all three files generated, contain run-specific paths, worker prompt contains required sections, no false automation claims | 05 | ☐ |
| 7.7 | CLI integration tests: happy path end-to-end, custom options, `--force` behavior, error cases (missing source, bad options, non-empty dir without force) | 02 | ☐ |
| 7.8 | Determinism test: same input + options → same output (except timestamp/run-specific fields) | 01 | ☐ |

**Dependencies:** Phase 6 (CLI is wired up).
**Lane:** Codex xhigh — well-specified test cases, benefits from thorough coverage.

---

## Phase 8: Polish & Validation

**Goal:** Final pass to ensure everything works end-to-end and docs are accurate.

| # | Task | Spec | Status |
|---|------|------|--------|
| 8.1 | Run `python -m pytest` and fix any failures | 06 | ☐ |
| 8.2 | Run CLI on a real-ish sample text (>50K chars) and inspect output manually | 02 | ☐ |
| 8.3 | Verify `RALPH.md` validation commands match reality | 06 | ☐ |
| 8.4 | Verify all acceptance criteria from all 6 specs are met | All | ☐ |
| 8.5 | Update `README.md` with usage instructions if needed | 01 | ☐ |

**Dependencies:** Phase 7 (tests exist and pass).
**Lane:** Claude Opus-4-6 — cross-cutting validation benefits from broad judgment.

---

## Dependency Graph

```
Phase 1 (Scaffolding)
  └─→ Phase 2 (Chunking)
        └─→ Phase 3 (Chunk Writer / Paths)
              ├─→ Phase 4 (Manifest)
              └─→ Phase 5 (Prompts) ← also depends on Phase 4
                    └─→ Phase 6 (CLI)
                          └─→ Phase 7 (Tests)
                                └─→ Phase 8 (Polish)
```

Phases 3 and 4 can partially parallelize. Phase 5 needs path conventions from 3 and manifest structure from 4. Phase 6 integrates everything.

## Implementation Order for Ralph Loop

Each Ralph iteration should complete one phase (or a meaningful sub-phase for Phase 2 and 7 which are larger). Suggested iteration sequence:

1. **Iteration 1:** Phase 1 (scaffolding) + Phase 2 (chunking) — these are independent enough to combine
2. **Iteration 2:** Phase 3 (chunk writer) + Phase 4 (manifest)
3. **Iteration 3:** Phase 5 (prompts) + Phase 6 (CLI wiring)
4. **Iteration 4:** Phase 7 (tests)
5. **Iteration 5:** Phase 8 (polish)

## Spec Coverage Matrix

| Spec | Phases |
|------|--------|
| 01 - Purpose & Boundaries | All (scope guard) |
| 02 - Ingestion CLI | 6, 7 |
| 03 - Boundary-Aware Chunking | 2, 3, 7 |
| 04 - Manifest & Run Layout | 3, 4, 7 |
| 05 - Prompt Templates | 5, 7 |
| 06 - Package Quality | 1, 7, 8 |

## Missing Specs

None identified. The six existing specs comprehensively cover all V1 requirements:
- Project boundaries and scope (01)
- CLI interface and UX (02)
- Chunking algorithm and behavior (03)
- Manifest schema and directory layout (04)
- Prompt generation and manual orchestration (05)
- Package structure, testing, and quality (06)

No additional spec files are needed for V1.
