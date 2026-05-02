0a. Study @AGENTS.md to discover the repo map and decide which docs matter for this iteration.
0b. Study @RALPH.md to learn build, validation, model-routing, and self-heal constraints for this project.
0c. Read each spec file in `specs/` that is relevant to the current implementation slice.
0d. Study @IMPLEMENTATION_PLAN.md.
0e. For reference, the application source code is in `src/*`.
0f. Study @HEAL_LOG.md (if present). Note files modified by recent fixes (last 10 entries). If your planned work touches these files, read the heal log entries first to avoid re-introducing fixed bugs. Add affected test cases to your verification checklist.
0g. TOOLING CONSTRAINT: You are running inside an OpenClaw agent. Your available tools are: `read`, `write`, `edit`, `exec`, `process`, `web_search`, `web_fetch`, `image`, `memory_search`, `memory_store`. The following Claude Code tools DO NOT EXIST and must never be called: `TaskOutput`, `TodoWrite`, `Agent`, `Glob`, `Grep`, `Write` (capital W), `Edit` (capital E), `Read` (capital R), `EnterPlanMode`, `ExitPlanMode`, `NotebookEdit`. Use `read` to read files, `write` to create/overwrite files, `edit` to modify files, and `exec` to run shell commands. For background task output use `process` with `action=poll` or `action=log`. Work directly — do not try to spawn subagents or workers.

1. Your task is to implement functionality per the specifications. Follow @IMPLEMENTATION_PLAN.md and choose the most important item to address. Before making changes, search the codebase to confirm the feature is not already implemented (use `exec` with grep/find, or `read` relevant files). Implement the feature directly — read the relevant source files, write the code, write the tests. Ultrathink.
2. After implementing functionality or resolving problems, run the tests using `exec`: `source .venv/bin/activate && python -m pytest -v`. If functionality is missing then it's your job to add it as per the application specifications.
3. When you discover issues, immediately update @IMPLEMENTATION_PLAN.md with your findings. When resolved, update and remove the item.
4. When the tests pass, update @IMPLEMENTATION_PLAN.md, then run `git add -A && git commit -m "description of changes"` then `git push`.
4b. After each successful commit, move to the next slice in IMPLEMENTATION_PLAN.md if the iteration has time remaining. Do not stop after one commit unless the iteration is running low on time or context.

5. If tests or build FAIL, enter the self-heal cycle. DO NOT exit the iteration immediately.
   5a. Capture diagnostic context: error output (stdout+stderr), exit code, git diff HEAD.
   5b. Check failure catalog for a known pattern match: first project-local (`failures/index.json`), then global (path from RALPH.md `global-catalog-path`). Match on error category + message substring.
   5c. If match found with documented fix procedure, apply it. If no match, diagnose from evidence. Require cited evidence for every claim in the diagnosis, no "it seems like" or "probably."
   5d. Classify severity: **auto** (deterministic fix, high confidence) / **assisted** (clear diagnosis but ambiguous fix, note for human) / **human** (cannot determine root cause or fix requires domain knowledge, escalate). If confidence is low, override auto to assisted.
   5e. For auto: apply fix, then re-run the failing test. Check for heal recursion: if this is the 2nd+ heal cycle and it touches the same files as a prior cycle, STOP and escalate.
   5f. If fix works: append to @HEAL_LOG.md (append-only, never edit existing entries), update failure catalog if new pattern, go to step 4 (commit). Note self-healed failures in the commit message.
   5g. If fix fails: increment retry counter. If retries remaining (max from RALPH.md `retry-budget`, default 3) and cost ceiling not exceeded, loop back to 5c with updated context including what was tried. If budget exhausted or cost exceeded: append to @HEAL_LOG.md, write escalation to @ESCALATIONS.md, mark task "blocked: pending human input" in @IMPLEMENTATION_PLAN.md, pick a different task or exit.
   5h. Self-heal MUST NOT modify test expectations to make tests pass (F020 defense). If diagnosis says the test is wrong, classify as "assisted."

99999. Important: When authoring documentation, capture the why, tests and implementation importance.
999999. Important: Single sources of truth, no migrations/adapters. If tests unrelated to your work fail, resolve them as part of the increment.
9999998. Before tagging or pushing, verify `git status --short` is empty. Do not modify tracked files after the commit. If you need to update @IMPLEMENTATION_PLAN.md or any docs, amend or create the commit first, then tag the clean commit.
9999999. As soon as there are no build or test errors create a git tag. Use plain numeric semver tags like `0.3.0` (next minor after V2's 0.2.0). Never a leading `v`.
99999999. You may add extra logging if required to debug issues.
999999999. Keep @IMPLEMENTATION_PLAN.md current with learnings, future work depends on this to avoid duplicating efforts. Update especially after finishing your turn.
9999999999. When you learn something new about how to run the application, update @RALPH.md but keep it brief. If the repo map or doc entrypoints changed, update @AGENTS.md too.
99999999999. For any bugs you notice, resolve them or document them in @IMPLEMENTATION_PLAN.md even if unrelated to the current piece of work.
999999999999. Implement functionality completely. Placeholders and stubs waste efforts and time redoing the same work.
9999999999999. When @IMPLEMENTATION_PLAN.md becomes large periodically clean out the items that are completed from the file.
99999999999999. If you find inconsistencies in the specs/* then update the specs.
999999999999999. IMPORTANT: Keep @AGENTS.md as the repo map and @RALPH.md operational only. Status updates and progress notes belong in `IMPLEMENTATION_PLAN.md`. A bloated RALPH.md pollutes every future loop's context.
