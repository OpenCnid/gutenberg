# Spec 14: Per-Chunk Task Materialization

V3 should generate concrete task files for each worker so humans and executors do not see ambiguous placeholders like `{chunk_number}`.

## Problem

V2 has one shared worker prompt. That is valid because actual chunk position data lives in each chunk file's YAML frontmatter, but it is awkward for humans and agents: the shared prompt necessarily contains placeholders such as `{chunk_number}` and `{chunk_id}`.

Executable orchestration needs one concrete task per worker. Each task should be copy-pasteable or executable without substitution.

## Scope

This spec creates deterministic task artifacts. It does not require launching workers; execution is covered by Spec 11.

## Command Shape

Canonical command:

```bash
gutenberg tasks <run-dir> [OPTIONS]
```

Required options:

- `--refresh`: overwrite/regenerate existing task files when source manifest changed or the operator wants a clean rebuild.
- `--dry-run`: show which tasks would be written without changing files.
- `--json`: machine-readable summary.

Task materialization may also run automatically before `gutenberg orchestrate <run-dir> --execute` if task files are missing or stale.

## Task Layout

V3 task files live under a new run-level `tasks/` directory:

```text
<run>/
  tasks/
    index.json
    synthesis.md
    workers/
      chunk-0001.worker.md
      chunk-0002.worker.md
```

Required paths:

- worker task pattern: `tasks/workers/{chunk_id}.worker.md`
- synthesis task: `tasks/synthesis.md`
- task index: `tasks/index.json`

The shared templates remain in `prompts/`:

```text
prompts/worker.md
prompts/synthesis.md
```

Task files are concrete task payloads generated from the shared templates, manifest, and chunk metadata.

## Worker Task Contents

Each worker task must include concrete, run-specific values:

- run title and author when available;
- run directory name;
- manifest path;
- chunk id;
- chunk number;
- total chunk count;
- chunk path;
- expected result path;
- previous/next context values from manifest/frontmatter;
- inferred section when available;
- required worker output format;
- instruction to analyze only the assigned chunk body;
- instruction to write `results/{chunk_id}.analysis.md` for that exact chunk id.

Example task heading:

```md
# Worker Task — chunk-0005 (Chunk 5 of 9)
```

A generated task file must not require the operator or executor to replace `{chunk_id}`, `{chunk_number}`, `{total_chunks}`, `{chunk_path}`, or `{result_path}` placeholders.

## Synthesis Task Contents

`tasks/synthesis.md` must include:

- run title and author when available;
- manifest path;
- total chunk count;
- expected synthesis output path;
- ordered list of expected worker result paths;
- current availability state for each worker result when generated;
- missing/failed/skipped chunks when known;
- instructions for full synthesis;
- instructions for partial synthesis when Spec 13 invokes it explicitly.

Synthesis tasks may be regenerated as worker result availability changes.

## Task Index

`tasks/index.json` is the machine-readable task catalog.

Minimum fields:

```json
{
  "schema_version": "1.0",
  "tasks": {
    "workers": [
      {
        "chunk_id": "chunk-0001",
        "chunk_number": 1,
        "total_chunks": 9,
        "chunk_path": "chunks/chunk-0001.md",
        "task_path": "tasks/workers/chunk-0001.worker.md",
        "result_path": "results/chunk-0001.analysis.md"
      }
    ],
    "synthesis": {
      "task_path": "tasks/synthesis.md",
      "result_path": "results/synthesis.md"
    }
  }
}
```

The index must use relative POSIX-style paths.

## Manifest and Status Integration

V3 should add task metadata additively when tasks are materialized.

Manifest may include:

```json
{
  "tasks": {
    "directory": "tasks",
    "index": "tasks/index.json",
    "worker_pattern": "tasks/workers/{chunk_id}.worker.md",
    "synthesis": "tasks/synthesis.md"
  }
}
```

Each chunk may include:

```json
{
  "id": "chunk-0001",
  "task_path": "tasks/workers/chunk-0001.worker.md"
}
```

Status chunk entries may include `task_path` once materialized.

Rules:

- Existing V1/V2 manifests without task metadata remain valid.
- Adding task metadata must not remove existing manifest fields.
- Task materialization may update manifest/status only with additive fields.
- Dry-run task materialization does not modify manifest/status/tasks.

## Determinism

For the same manifest and task-generation version, generated task files should be byte-for-byte deterministic.

Rules:

- No generated timestamps in task files or `tasks/index.json` by default.
- Worker task order follows manifest chunk order.
- JSON is pretty-printed with stable key ordering where practical.
- Paths are relative to the run directory.
- Existing task files are left unchanged when generated content would be identical.

## Staleness

A task is stale when:

- the expected task file is missing;
- the manifest chunk metadata changed;
- the shared task template version changed;
- the result path convention changed;
- the task index disagrees with manifest chunk ids.

`gutenberg tasks <run-dir>` should report stale tasks. `--refresh` should rewrite them.

## Compatibility

- The existing shared `prompts/worker.md` remains available and valid.
- Existing V2 worker prompt placeholders are not a blocker for V2 compatibility.
- V1/V2 runs can gain task files by running `gutenberg tasks <run-dir>`.
- Manual operators can still use shared prompts if they prefer.

## Acceptance Criteria

- `gutenberg tasks <run>` writes `tasks/index.json`, `tasks/synthesis.md`, and one worker task per manifest chunk.
- Each worker task contains concrete chunk id, chunk number, total chunks, chunk path, and result path.
- Worker task files contain no unresolved `{chunk_id}`, `{chunk_number}`, `{total_chunks}`, `{chunk_path}`, or `{result_path}` placeholders.
- Task files are deterministic for the same run metadata.
- `--dry-run` reports planned task files without changing the run directory.
- `--refresh` rewrites stale task files and leaves unchanged files alone when content matches.
- `tasks/index.json` is valid JSON and uses relative POSIX-style paths.
- Manifest/status task metadata is additive and does not break V1/V2 validation.
- `gutenberg orchestrate <run> --execute` can use task files without requiring manual placeholder substitution.
- Shared prompt files under `prompts/` remain present and usable.
