"""Per-chunk task materialization — Spec 14.

Generates concrete, deterministic task files for each worker and for synthesis.
No placeholders remain in generated tasks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gutenberg import paths as P


# ---------------------------------------------------------------------------
# Worker task generation
# ---------------------------------------------------------------------------

def generate_worker_task(
    manifest: dict[str, Any],
    chunk: dict[str, Any],
    run_dir_name: str,
) -> str:
    """Render a concrete worker task markdown for one chunk.

    Uses manifest metadata + chunk entry values.  No ``{chunk_number}``
    placeholders — every value is baked in.
    """
    title = manifest.get("source", {}).get("title", "") or "Untitled"
    author = manifest.get("source", {}).get("author", "")

    chunk_id = chunk["id"]
    chunk_number = chunk["chunk_number"]
    total_chunks = chunk["total_chunks"]
    chunk_path = chunk["path"]
    result_path = f"{P.RESULTS_DIR}/{chunk_id}.analysis.md"

    prev_context = chunk.get("prev_context", "")
    next_context = chunk.get("next_context", "")
    inferred_section = chunk.get("inferred_section", "")

    lines: list[str] = []
    lines.append(f"# Worker Task — {chunk_id} (Chunk {chunk_number} of {total_chunks})")
    lines.append("")

    lines.append("## Run Context")
    lines.append("")
    lines.append(f"- **Title:** {title}")
    if author:
        lines.append(f"- **Author:** {author}")
    lines.append(f"- **Run directory:** `{run_dir_name}/`")
    lines.append(f"- **Manifest:** `{P.MANIFEST_FILENAME}`")
    lines.append("")

    lines.append("## Chunk Assignment")
    lines.append("")
    lines.append(f"- **Chunk ID:** {chunk_id}")
    lines.append(f"- **Chunk number:** {chunk_number} of {total_chunks}")
    lines.append(f"- **Chunk path:** `{chunk_path}`")
    lines.append(f"- **Result path:** `{result_path}`")
    if inferred_section:
        lines.append(f"- **Inferred section:** {inferred_section}")
    lines.append("")

    lines.append("## Neighboring Context")
    lines.append("")
    if prev_context:
        lines.append(f"**Previous chunk ends with:**")
        lines.append(f"> {prev_context}")
    else:
        lines.append("**Previous chunk ends with:** Start of text")
    lines.append("")
    if next_context:
        lines.append(f"**Next chunk begins with:**")
        lines.append(f"> {next_context}")
    else:
        lines.append("**Next chunk begins with:** End of text")
    lines.append("")

    lines.append("## Instructions")
    lines.append("")
    lines.append("1. Read the chunk file at the path above carefully.")
    lines.append("2. Analyze **only** the assigned chunk body. Do not reference or assume content from other chunks.")
    lines.append("3. Use neighboring context for continuity awareness only.")
    lines.append("4. Write your analysis in the structured format below.")
    lines.append(f"5. Save your output to `{result_path}`.")
    lines.append("")

    lines.append("## Important Rules")
    lines.append("")
    lines.append("- Analyze **only** the assigned chunk.")
    lines.append("- Preserve important quotes with enough surrounding context to be meaningful.")
    lines.append("- Clearly distinguish between **source claims** and **your interpretation**.")
    lines.append("- When uncertain, note the uncertainty rather than inventing cross-chunk context.")
    lines.append("- If you do not have file write access, return the analysis in the format below for a human to save.")
    lines.append("")

    lines.append("## Required Output Format")
    lines.append("")
    lines.append("Write your analysis as structured markdown with these sections:")
    lines.append("")
    lines.append("```markdown")
    lines.append("# Chunk Summary")
    lines.append("")
    lines.append("A concise summary of the main content and arguments in this chunk.")
    lines.append("")
    lines.append("# Key Claims / Ideas")
    lines.append("")
    lines.append("- Claim or idea 1")
    lines.append("- Claim or idea 2")
    lines.append("")
    lines.append("# Important Quotes")
    lines.append("")
    lines.append('> "Quote 1" (with enough context to be meaningful)')
    lines.append("")
    lines.append("# Entities / Concepts")
    lines.append("")
    lines.append("- Entity or concept 1: brief description")
    lines.append("")
    lines.append("# Open Questions")
    lines.append("")
    lines.append("- Question raised by this chunk")
    lines.append("")
    lines.append("# Connections To Other Chunks")
    lines.append("")
    lines.append("- Potential connection 1")
    lines.append("")
    lines.append("# Synthesis Notes")
    lines.append("")
    lines.append("Any observations that would help a synthesizer combine this analysis with others.")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Synthesis task generation
# ---------------------------------------------------------------------------

def generate_synthesis_task(
    manifest: dict[str, Any],
    status: dict[str, Any] | None,
    run_dir_name: str,
    partial: bool = False,
) -> str:
    """Render the synthesis task with current worker result availability."""
    title = manifest.get("source", {}).get("title", "") or "Untitled"
    author = manifest.get("source", {}).get("author", "")
    chunks = manifest.get("chunks", [])
    total_chunks = len(chunks)
    synthesis_output = f"{P.RESULTS_DIR}/synthesis.md"

    chunk_statuses = status.get("chunks", {}) if status else {}

    lines: list[str] = []
    lines.append(f"# Synthesis Task — {title}")
    lines.append("")

    lines.append("## Run Context")
    lines.append("")
    lines.append(f"- **Title:** {title}")
    if author:
        lines.append(f"- **Author:** {author}")
    lines.append(f"- **Run directory:** `{run_dir_name}/`")
    lines.append(f"- **Manifest:** `{P.MANIFEST_FILENAME}`")
    lines.append(f"- **Total chunks:** {total_chunks}")
    lines.append(f"- **Synthesis output:** `{synthesis_output}`")
    lines.append("")

    lines.append("## Worker Results")
    lines.append("")

    available_count = 0
    missing_chunks: list[str] = []
    failed_chunks: list[str] = []
    skipped_chunks: list[str] = []

    for chunk in chunks:
        cid = chunk["id"]
        chunk_number = chunk["chunk_number"]
        result_path = f"{P.RESULTS_DIR}/{cid}.analysis.md"
        cs = chunk_statuses.get(cid, {})
        state = cs.get("state", "pending")

        if state == "done":
            mark = "[available]"
            available_count += 1
        elif state == "failed":
            mark = "[FAILED]"
            failed_chunks.append(cid)
        elif state == "skipped":
            mark = "[SKIPPED]"
            skipped_chunks.append(cid)
        else:
            mark = "[missing]"
            missing_chunks.append(cid)

        lines.append(f"- `{result_path}` (chunk {chunk_number}) {mark}")

    lines.append("")
    lines.append(f"**Available:** {available_count} of {total_chunks}")
    lines.append("")

    if missing_chunks or failed_chunks or skipped_chunks:
        lines.append("## Gaps")
        lines.append("")
        if missing_chunks:
            lines.append(f"**Missing results:** {', '.join(missing_chunks)}")
        if failed_chunks:
            lines.append(f"**Failed chunks:** {', '.join(failed_chunks)}")
        if skipped_chunks:
            lines.append(f"**Skipped chunks:** {', '.join(skipped_chunks)}")
        lines.append("")

    if partial:
        lines.append("## Partial Synthesis")
        lines.append("")
        lines.append("This is a **partial synthesis**. Not all worker results are available.")
        lines.append("Synthesize from the available results and explicitly note gaps.")
        lines.append("Mark sections where missing chunk analyses may affect completeness.")
        lines.append("")

    lines.append("## Instructions")
    lines.append("")
    lines.append("### Step 1: Check for missing analyses")
    lines.append("")
    lines.append("Before synthesizing, verify which chunk analysis files are present.")
    lines.append("List any missing chunks explicitly — do not silently ignore gaps.")
    lines.append("")
    lines.append("### Step 2: Read all available analyses")
    lines.append("")
    lines.append(f"Study every available `{P.RESULTS_DIR}/*.analysis.md` file.")
    lines.append("")
    lines.append("### Step 3: Synthesize")
    lines.append("")
    lines.append("Produce a coherent synthesis that:")
    lines.append("")
    lines.append("- Integrates key claims and ideas across all chunks.")
    lines.append("- Preserves important disagreements, ambiguities, and open questions.")
    lines.append("- Identifies themes and patterns that span multiple chunks.")
    lines.append("- Includes a compact list of the strongest quotes/evidence from across the text.")
    lines.append("- Notes where chunk boundaries may have affected analysis.")
    lines.append("")
    lines.append(f"### Step 4: Write output to `{synthesis_output}`")
    lines.append("")

    lines.append("## Output Format")
    lines.append("")
    lines.append("```markdown")
    lines.append(f"# Synthesis — {title}")
    lines.append("")
    lines.append("## Missing Chunks")
    lines.append("")
    lines.append("List any chunk analyses that were not available.")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("A concise overview of the entire text's main arguments and contributions.")
    lines.append("")
    lines.append("## Key Themes")
    lines.append("")
    lines.append("### Theme 1")
    lines.append("Description and supporting evidence from multiple chunks.")
    lines.append("")
    lines.append("## Critical Analysis")
    lines.append("")
    lines.append("Strengths, weaknesses, gaps, and contradictions in the source material.")
    lines.append("")
    lines.append("## Key Quotes")
    lines.append("")
    lines.append("The most important quotes from across the text, with chunk references.")
    lines.append("")
    lines.append("## Open Questions")
    lines.append("")
    lines.append("Unresolved questions, ambiguities, or areas requiring further investigation.")
    lines.append("")
    lines.append("## Methodology Notes")
    lines.append("")
    lines.append("Any observations about how the chunking or analysis process may have affected the synthesis.")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Task index
# ---------------------------------------------------------------------------

def build_task_index(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build ``tasks/index.json`` content from the manifest."""
    chunks = manifest.get("chunks", [])
    total_chunks = len(chunks)

    workers = []
    for chunk in chunks:
        cid = chunk["id"]
        workers.append({
            "chunk_id": cid,
            "chunk_number": chunk["chunk_number"],
            "total_chunks": total_chunks,
            "chunk_path": chunk["path"],
            "task_path": f"{P.TASKS_WORKERS_DIR}/{cid}.worker.md",
            "result_path": f"{P.RESULTS_DIR}/{cid}.analysis.md",
        })

    return {
        "schema_version": "1.0",
        "tasks": {
            "workers": workers,
            "synthesis": {
                "task_path": P.TASKS_SYNTHESIS,
                "result_path": f"{P.RESULTS_DIR}/synthesis.md",
            },
        },
    }


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------

def materialize_tasks(
    manifest: dict[str, Any],
    status: dict[str, Any] | None,
    run_dir: Path,
    refresh: bool = False,
) -> dict[str, Any]:
    """Orchestrate task generation: write worker tasks, synthesis task, index.

    When *refresh* is ``False``, skip files whose content would be identical.
    When *refresh* is ``True``, always write.

    Returns a summary dict with counts of written/skipped files.
    """
    run_dir_name = run_dir.name
    chunks = manifest.get("chunks", [])

    # Ensure directories
    P.tasks_workers_dir(run_dir).mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    worker_paths: list[str] = []

    # Worker tasks
    for chunk in chunks:
        cid = chunk["id"]
        task_content = generate_worker_task(manifest, chunk, run_dir_name)
        task_path = P.worker_task_path(run_dir, cid)
        worker_paths.append(str(task_path.relative_to(run_dir)))

        if not refresh and task_path.exists():
            existing = task_path.read_text(encoding="utf-8")
            if existing == task_content:
                skipped += 1
                continue

        task_path.write_text(task_content, encoding="utf-8")
        written += 1

    # Synthesis task
    synth_content = generate_synthesis_task(manifest, status, run_dir_name)
    synth_path = P.synthesis_task_path(run_dir)
    if not refresh and synth_path.exists():
        existing = synth_path.read_text(encoding="utf-8")
        if existing == synth_content:
            skipped += 1
        else:
            synth_path.write_text(synth_content, encoding="utf-8")
            written += 1
    else:
        synth_path.write_text(synth_content, encoding="utf-8")
        written += 1

    # Task index
    index_content = build_task_index(manifest)
    index_text = json.dumps(index_content, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    index_path = P.tasks_index_path(run_dir)
    if not refresh and index_path.exists():
        existing = index_path.read_text(encoding="utf-8")
        if existing == index_text:
            skipped += 1
        else:
            index_path.write_text(index_text, encoding="utf-8")
            written += 1
    else:
        index_path.write_text(index_text, encoding="utf-8")
        written += 1

    return {
        "written": written,
        "skipped": skipped,
        "total_files": len(chunks) + 2,  # workers + synthesis + index
        "worker_count": len(chunks),
    }


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------

def check_staleness(manifest: dict[str, Any], run_dir: Path) -> list[dict[str, str]]:
    """Check each expected task file against the current manifest.

    Returns a list of dicts with ``chunk_id``, ``task_path``, and ``reason``
    for each stale or missing entry.
    """
    run_dir_name = run_dir.name
    chunks = manifest.get("chunks", [])
    stale: list[dict[str, str]] = []

    for chunk in chunks:
        cid = chunk["id"]
        task_path = P.worker_task_path(run_dir, cid)

        if not task_path.exists():
            stale.append({
                "chunk_id": cid,
                "task_path": str(task_path.relative_to(run_dir)),
                "reason": "missing",
            })
            continue

        expected = generate_worker_task(manifest, chunk, run_dir_name)
        actual = task_path.read_text(encoding="utf-8")
        if actual != expected:
            stale.append({
                "chunk_id": cid,
                "task_path": str(task_path.relative_to(run_dir)),
                "reason": "content_changed",
            })

    # Check synthesis task
    synth_path = P.synthesis_task_path(run_dir)
    if not synth_path.exists():
        stale.append({
            "chunk_id": "_synthesis",
            "task_path": str(synth_path.relative_to(run_dir)),
            "reason": "missing",
        })

    # Check index
    index_path = P.tasks_index_path(run_dir)
    if not index_path.exists():
        stale.append({
            "chunk_id": "_index",
            "task_path": str(index_path.relative_to(run_dir)),
            "reason": "missing",
        })
    else:
        expected_index = json.dumps(
            build_task_index(manifest), indent=2, sort_keys=True, ensure_ascii=False
        ) + "\n"
        actual_index = index_path.read_text(encoding="utf-8")
        if actual_index != expected_index:
            stale.append({
                "chunk_id": "_index",
                "task_path": str(index_path.relative_to(run_dir)),
                "reason": "content_changed",
            })

    return stale
