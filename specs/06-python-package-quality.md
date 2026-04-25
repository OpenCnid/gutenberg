# Python Package Quality

Gutenberg should be a small, boring Python project that Ralph can safely iterate on.

## Packaging

V1 should use a conventional Python package layout. The exact tooling may be chosen during implementation, but the repo should support:

- Running the CLI from the repository.
- Running tests locally.
- Importing chunking and manifest logic from tests.

A simple layout is acceptable:

```text
src/
  gutenberg/
    __init__.py
    cli.py
    chunking.py
    manifest.py
    prompts.py
    paths.py

tests/
  ...
```

## Dependencies

- Prefer Python standard library for V1.
- Avoid network dependencies.
- Avoid heavyweight NLP/tokenizer dependencies unless there is a clear reason.
- If a dependency is introduced, document why it is worth the added surface area.

## Tests

Tests should cover:

- CLI happy path on a small sample text.
- Default options.
- Custom chunk size and overlap.
- Boundary-aware chunking behavior.
- Manifest required fields and paths.
- Prompt file generation.
- Error handling for invalid options and missing source files.

## Validation Commands

Ralph should keep validation commands current in `RALPH.md`. Initial expected commands:

- Tests: `python -m pytest`
- Typecheck: optional until typing tooling exists
- Lint: optional until lint tooling exists

If pytest is not installed or not chosen, Ralph should update `RALPH.md` with the actual test command it creates.

## Acceptance Criteria

- Project logic is separated enough that tests do not need to shell out for every assertion.
- Tests use temporary directories and do not write into real project runs.
- The project can run fully offline.
- The validation command in `RALPH.md` matches reality.
- Generated artifacts are deterministic enough to snapshot or assert structurally in tests.
