0a. Study @AGENTS.md to discover the repo map and decide which docs matter for this iteration.
0b. Study @RALPH.md to learn build, validation, model-routing, and self-heal constraints for this project.
0c. Study `specs/*` with up to 500 parallel OpenClaw subagents to learn the application specifications.
0d. Study @IMPLEMENTATION_PLAN.md.
0e. For reference, the application source code is in `src/*`.
0f. Study @HEAL_LOG.md (if present). Note files modified by recent fixes (last 10 entries). If your planned work touches these files, read the heal log entries first to avoid re-introducing fixed bugs. Add affected test cases to your verification checklist.

1. Your task is to implement functionality per the specifications using parallel workers. Follow @IMPLEMENTATION_PLAN.md and choose the most important item to address. Before making changes, search the codebase (don't assume not implemented) using parallel OpenClaw subagents. You may use up to 500 parallel OpenClaw subagents for searches and reads and only 1 worker for build/tests. Use Claude Opus-4-6 via the OpenClaw native lane on `lil-dario/claude-opus-4-6` for main coordination, broad parallel orchestration, and situations where the codebase still has gaps, assumptions, or under-specified edges that need to be resolved while moving forward. Use Codex `gpt-5.5` in xhigh thinking mode as the normal companion lane for precise end-to-end execution on tightly scoped changes that can be clearly explained and pinpointed when Codex is available. It is also strong for architecture decisions, code review, debugging, and deep analysis.
2. After implementing functionality or resolving problems, run the tests for that unit of code that was improved. If functionality is missing then it's your job to add it as per the application specifications. Ultrathink.
3. When you discover issues, immediately update @IMPLEMENTATION_PLAN.md with your findings using a worker. When resolved, update and remove the item.
4. When the tests pass, update @IMPLEMENTATION_PLAN.md, then `git add -A` then `git commit` with a message describing the changes. After the commit, `git push`.
4b. This smoke-friendly loop is single-slice only. After you have one successful implementation commit and one matching semver tag pushed, STOP. Do not make a second cleanup, polish, documentation, or regression-only follow-up commit in the same iteration.
4c. If `0.0.1` already exists on `HEAD`, treat that as a completed slice for this fixture. Do not create `0.0.2+`, do not add a follow-up tag, and do not keep iterating just because you found a possible nice-to-have improvement after the successful tagged state.

5. If tests or build FAIL, enter the self-heal cycle. DO NOT exit the iteration immediately.
   5a. Capture diagnostic context: error output (stdout+stderr), exit code, `git diff HEAD`, and run each context hook from RALPH.md `## Self-Heal Configuration`. Validate each hook produced non-empty output (F001 defense).
   5b. Check failure catalog for a known pattern match: first project-local (`failures/index.json`), then global (path from RALPH.md `global-catalog-path`). Match on error category + message substring.
   5c. If match found with documented fix procedure, apply it. If no match, diagnose from evidence using Claude Opus-4-6 via the OpenClaw native lane on `lil-dario/claude-opus-4-6`. Require cited evidence for every claim in the diagnosis, no "it seems like" or "probably."
   5d. Classify severity: **auto** (deterministic fix, high confidence) / **assisted** (clear diagnosis but ambiguous fix, note for human) / **human** (cannot determine root cause or fix requires domain knowledge, escalate). If confidence is low, override auto to assisted.
   5e. For auto: apply fix using 1 worker, then YOU re-run the failing test (the fixing worker MUST NOT verify its own work). Check for heal recursion: if this is the 2nd+ heal cycle and it touches the same files as a prior cycle, STOP and escalate.
   5f. If fix works: append to @HEAL_LOG.md (append-only, never edit existing entries), update failure catalog if new pattern, continue to step 4 (commit). Note self-healed failures in the commit message.
   5g. If fix fails: increment retry counter. If retries remaining (max from RALPH.md `retry-budget`, default 3) and cost ceiling not exceeded, loop back to 5c with updated context including what was tried. If budget exhausted or cost exceeded: append to @HEAL_LOG.md, write escalation to @ESCALATIONS.md (all 6 fields: summary, tier, context, attempts, hypothesis, suggested action), mark task "blocked: pending human input" in @IMPLEMENTATION_PLAN.md, pick a different task or exit.
   5h. Self-heal MUST NOT modify test expectations to make tests pass (F020 defense). If diagnosis says the test is wrong, classify as "assisted."
   Self-heal canonical reference: specs/self-heal.md (or skill reference). This prompt section is a compressed derivative, the spec wins on any conflict.

99999. Important: When authoring documentation, capture the why, tests and implementation importance.
999999. Important: Single sources of truth, no migrations/adapters. If tests unrelated to your work fail, resolve them as part of the increment.
9999998. Before tagging or pushing, verify `git status --short` is empty. Do not modify tracked files after the commit. If you need to update @IMPLEMENTATION_PLAN.md or any docs, amend or create the commit first, then tag the clean commit.
9999999. As soon as there are no build or test errors create a git tag. Use plain numeric semver tags like `0.0.1`, never a leading `v`. If there are no git tags start at 0.0.0 and increment patch by 1, for example 0.0.1 if 0.0.0 does not exist.
9999999a. In the smoke fixture, the expected terminal state is exactly one post-fixture implementation commit and tag `0.0.1` on that commit. Do not add extra regression coverage, plan cleanups, or documentation-only commits after `0.0.1` is created.
99999999. You may add extra logging if required to debug issues.
999999999. Keep @IMPLEMENTATION_PLAN.md current with learnings using a worker, future work depends on this to avoid duplicating efforts. Update especially after finishing your turn.
9999999999. When you learn something new about how to run the application, update @RALPH.md using a worker but keep it brief. If the repo map or doc entrypoints changed, update @AGENTS.md too.
99999999999. For any bugs you notice, resolve them or document them in @IMPLEMENTATION_PLAN.md using a worker even if it is unrelated to the current piece of work.
999999999999. Implement functionality completely. Placeholders and stubs waste efforts and time redoing the same work.
9999999999999. When @IMPLEMENTATION_PLAN.md becomes large periodically clean out the items that are completed from the file using a worker.
99999999999999. If you find inconsistencies in the specs/* then use Claude Opus-4-6 via the OpenClaw native lane on `lil-dario/claude-opus-4-6` with ultrathink requested to update the specs.
999999999999999. IMPORTANT: Keep @AGENTS.md as the repo map and @RALPH.md operational only. Status updates and progress notes belong in `IMPLEMENTATION_PLAN.md`. A bloated RALPH.md pollutes every future loop's context.
