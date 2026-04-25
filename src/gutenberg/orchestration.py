"""Orchestration planning — automated worker-to-synthesis pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gutenberg import paths as P


def build_plan(
    manifest: dict[str, Any],
    status: dict[str, Any],
    skip_failed: bool = False,
) -> dict[str, Any]:
    """Analyze chunks and classify into pending/done/failed/skipped.

    Returns a structured plan dict.
    """
    chunks = manifest.get("chunks", [])
    chunk_status = status.get("chunks", {})

    pending: list[dict[str, Any]] = []
    done: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for chunk in chunks:
        cid = chunk["id"]
        entry = chunk_status.get(cid, {})
        state = entry.get("state", "pending")

        info = {"id": cid, "path": chunk.get("path", "")}

        if state == "done":
            done.append(info)
        elif state == "failed":
            if skip_failed:
                skipped.append(info)
            else:
                # Retry failed chunks — treat as pending
                pending.append(info)
        else:
            # pending, running, missing — all need work
            pending.append(info)

    blockers: list[str] = []
    if pending:
        blockers.append(f"{len(pending)} chunk(s) still need processing")
    if failed and not skip_failed:
        # Already included in pending for retry
        pass
    if skipped:
        blockers.append(f"{len(skipped)} failed chunk(s) skipped")

    synthesis_ready = len(pending) == 0 and len(skipped) == 0

    return {
        "pending": pending,
        "done": done,
        "failed": failed,
        "skipped": skipped,
        "synthesis_ready": synthesis_ready,
        "blockers": blockers,
    }


def format_worker_command(run_dir: Path, chunk: dict[str, Any]) -> str:
    """Generate the textual command/instruction for one worker."""
    cid = chunk["id"]
    chunk_path = run_dir / chunk.get("path", f"{P.CHUNKS_DIR}/{cid}.md")
    worker_prompt = P.worker_prompt_path(run_dir)
    result_path = P.worker_result_path(run_dir, cid)

    return (
        f"# Worker: {cid}\n"
        f"# Read prompt: {worker_prompt}\n"
        f"# Read chunk:  {chunk_path}\n"
        f"# Write result to: {result_path}\n"
    )


def format_plan_text(plan: dict[str, Any], run_dir: Path) -> str:
    """Human-readable plan output."""
    lines: list[str] = []
    lines.append(f"Orchestration Plan — {run_dir.name}")
    lines.append("=" * 40)
    lines.append("")

    total = len(plan["pending"]) + len(plan["done"]) + len(plan["failed"]) + len(plan["skipped"])
    lines.append(f"Total chunks: {total}")
    lines.append(f"  Done:    {len(plan['done'])}")
    lines.append(f"  Pending: {len(plan['pending'])}")
    if plan["failed"]:
        lines.append(f"  Failed:  {len(plan['failed'])}")
    if plan["skipped"]:
        lines.append(f"  Skipped: {len(plan['skipped'])}")
    lines.append("")

    if plan["pending"]:
        lines.append("Pending workers:")
        for chunk in plan["pending"]:
            lines.append(f"  - {chunk['id']} ({chunk['path']})")
        lines.append("")

    if plan["done"]:
        lines.append("Done (skipped):")
        for chunk in plan["done"]:
            lines.append(f"  - {chunk['id']}")
        lines.append("")

    if plan["synthesis_ready"]:
        lines.append("Synthesis: READY")
        synthesis_prompt = P.synthesis_prompt_path(run_dir)
        lines.append(f"  Run synthesis using: {synthesis_prompt}")
    else:
        lines.append("Synthesis: NOT READY")
        for b in plan["blockers"]:
            lines.append(f"  Blocker: {b}")

    lines.append("")
    return "\n".join(lines)


def format_plan_json(plan: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Machine-readable plan output."""
    return {
        "run_dir": str(run_dir),
        "pending": plan["pending"],
        "done": plan["done"],
        "failed": plan["failed"],
        "skipped": plan["skipped"],
        "synthesis_ready": plan["synthesis_ready"],
        "blockers": plan["blockers"],
        "summary": {
            "total": len(plan["pending"]) + len(plan["done"]) + len(plan["failed"]) + len(plan["skipped"]),
            "pending": len(plan["pending"]),
            "done": len(plan["done"]),
            "failed": len(plan["failed"]),
            "skipped": len(plan["skipped"]),
        },
    }


def generate_script(plan: dict[str, Any], run_dir: Path) -> str:
    """Generate a shell script with one command per pending worker."""
    lines: list[str] = []
    lines.append("#!/usr/bin/env bash")
    lines.append("set -e")
    lines.append("")
    lines.append(f"# Orchestration script for {run_dir.name}")
    lines.append(f"# Pending workers: {len(plan['pending'])}")
    lines.append("")

    worker_prompt = P.worker_prompt_path(run_dir)

    for chunk in plan["pending"]:
        cid = chunk["id"]
        chunk_path = run_dir / chunk.get("path", f"{P.CHUNKS_DIR}/{cid}.md")
        result_path = P.worker_result_path(run_dir, cid)

        lines.append(f"# --- Worker: {cid} ---")
        lines.append(f"# Prompt: {worker_prompt}")
        lines.append(f"# Chunk:  {chunk_path}")
        lines.append(f"# Output: {result_path}")
        lines.append(f"echo \"Processing {cid}...\"")
        lines.append(f"# <your-agent-command> --prompt \"{worker_prompt}\" --input \"{chunk_path}\" --output \"{result_path}\"")
        lines.append(f"# TODO: update status.json after each worker")
        lines.append("")

    if plan["synthesis_ready"]:
        synthesis_prompt = P.synthesis_prompt_path(run_dir)
        lines.append("# --- Synthesis ---")
        lines.append(f"echo \"All workers complete. Running synthesis...\"")
        lines.append(f"# <your-agent-command> --prompt \"{synthesis_prompt}\" --output \"{P.results_dir(run_dir) / 'synthesis.md'}\"")
    else:
        lines.append("# Synthesis not ready — complete pending workers first.")

    lines.append("")
    return "\n".join(lines)


def check_synthesis(
    plan: dict[str, Any],
    manifest: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    """Report whether synthesis is ready and output synthesis command if so."""
    result: dict[str, Any] = {
        "ready": plan["synthesis_ready"],
        "blockers": plan["blockers"],
    }

    if plan["synthesis_ready"]:
        synthesis_prompt = P.synthesis_prompt_path(run_dir)
        result["synthesis_prompt"] = str(synthesis_prompt)
        result["synthesis_output"] = str(P.synthesis_result_path(run_dir))
        result["command"] = (
            f"# Run synthesis using:\n"
            f"# <your-agent-command> --prompt \"{synthesis_prompt}\" "
            f"--output \"{P.synthesis_result_path(run_dir)}\""
        )

    return result
