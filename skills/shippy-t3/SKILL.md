---
name: shippy-t3
description: Plan and build code changes in T3 with Claude Opus orchestration, fresh Sol implementation agents, and Luna for mechanical stages and command verification. Use when the user invokes shippy-t3 or requests the hybrid Claude/OpenAI shippy workflow.
---

# Shippy for T3

Claude Opus investigates, designs the roadmap, writes stage specs and assesses the final result. Sol builds ordinary stages; Luna handles mechanical stages and runs verification commands. This variant is unbenchmarked; do not promise savings or equivalent quality.

## Runtime and model contract

- Preferred orchestrator: a Claude Opus main session (`claude-opus-5-5`). A skill cannot switch the active session. If invoked under another model, explain that mismatch before execution and ask whether to continue with that orchestrator or let the user select Opus. Never silently add a second planning layer or create a new top-level thread.
- Default builder: `gpt-6-sol`, `reasoningEffort: medium`. Use `gpt-6-luna` at `medium` only for mechanical or tightly specified stages with little implementation judgment (renames, docs, config, fixtures, or wiring existing functions). Sol owns stages with meaningful logic, debugging, or interacting components, including high-risk work.
- Baseline and final command verifier: `gpt-6-luna`, `reasoningEffort: medium`. Running tests is not an independent correctness review: Claude must assess whether the implementation satisfies the requirements and whether the checks cover the changed contracts.
- Before the first dispatch, call T3 `orchestrator_capabilities` once per thread. Reuse its result; repeat only after an error or user-named provider change. Resolve provider instance IDs and confirm the exact models and effort options. Do not replace Sol with another generation or substitute providers/models without the user's agreement.
- Requires T3 `delegate_task`, repository access and command execution. If unavailable, report the missing capability; do not fall back to native agents, Workflow or a CLI. A downloaded skill does not enable T3 or provider authentication.
- Explicitly delegate each implementation stage and baseline/final verification through T3. Run stages sequentially with `isolation: shared`; never run two writers together. Children must not delegate.
- Read [references/stage-executor.md](references/stage-executor.md) when preparing a builder and [references/plan-verifier.md](references/plan-verifier.md) when preparing verification. Resolve absolute paths before dispatch. Both references ship inside this skill; no other skill installation is required.

## Planning and authorization

1. Read project instructions, inspect git status and record branch and `START_SHA`. Preserve existing edits and staged files. Stop for an in-progress merge/rebase/cherry-pick or detached HEAD before making commits.
2. Investigate relevant code, existing tests and exact verification commands. Prefer targeted searches. Use quiet test flags only when supported and failure details remain visible. State a falsifiable root cause for bugs; if uncertain, make the first stage diagnostic.
3. Use one stage for a small, obvious change (roughly three files, no migration or API change). Otherwise write a roadmap with dependency-ordered stages, each independently verifiable and roughly eight files or fewer. Set shared signatures, error behavior and schema contracts before building.
4. Clarify only material decisions that code and conventional defaults cannot settle. Use the host's question tool when available, recommended choice first, preserving free-text answers. Use only question and plan-mode tools actually exposed by the host.
5. Respect authorization already supplied. If the user asked to implement, proceed with a brief visible plan using conventional defaults. If they asked to approve a plan first or confirm each stage, show the concrete plan and wait at those gates. Record `Approval: auto | each stage | plan only`. A missing reply is not approval.
6. Write `.plans/<slug>.md` and exclude it locally through the repository's git exclude file if needed. Keep it out of commits. Record commands, conventions, non-goals, existing changes and baseline results. Use `git rev-parse --git-path info/exclude` rather than assuming `.git` is a directory.
7. Record `Commits: per stage | none` from the user's instructions and repository rules. Prefer per-stage local commits when authorized. A no-commit instruction does not prevent building; record stage completion and refresh anchors from the working tree instead.

## Stage loop

1. Run baseline verification once via a fresh Luna verifier. Recheck status first for changes since planning. Record failures, command exit codes and unavailable checks; builders do not repeat the baseline.
2. Write the next stage spec only after the previous stage finishes. Read its report and relevant changes; refresh edit anchors from actual files. Record HEAD and any relevant uncommitted changes. Never use stale HEAD snippets for working-tree edits.
3. Each stage spec contains:
   - Goal, exact file paths and symbols; allowed scope and non-goals.
   - Public contracts: exact signatures, types, error behavior and boundaries.
   - Numbered edits with current code anchors of at most 15 lines each.
   - Black-box cases: inputs/actions, observable expectations and test locations.
   - White-box cases only for meaningful internal paths not already covered; `none` is valid.
   - Copy-paste verification commands, expected results and baseline exceptions.
   - Executor model and reasoning effort, with a short reason for Luna routing.
   - Commit policy and exact Conventional Commit message if applicable.
   Do not include full files or sample implementations. Docs and mechanical changes may use inspection instead of artificial tests.
4. Honor any requested stage gate. Show the files, behavior, checks and executor before asking. Otherwise dispatch immediately with the plan ranges and executor reference; never copy the entire conversation to a builder.
5. Follow T3's returned lifecycle instructions (below). Do not start the next stage while a writer remains active.
6. Inspect the report and targeted evidence: status, diff stat and commit identity when applicable. Investigate missing checks, unexpected files or contract deviations; do not routinely reread all code or rerun passing commands.
7. If blocked, correct a settled spec/anchor/command gap and create one fresh replacement task, identifying partial edits it owns. Cancel the old task first if still active. For a second blocker or a new product decision, return the concrete blocker to the user. Do not change models silently; a Luna-to-Sol escalation requires agreement unless already authorized in the plan.
8. After the last stage, run final verification via a fresh Luna verifier. A new failure gets a bounded fix stage; environmental blockers must remain explicitly reported, not labeled passing.

### T3 dispatch and lifecycle

Use `delegate_task` with the provider ID from capabilities, options in `target.options`, and a self-contained task. For example, with provider ID `codex`:

```json
{
  "title": "Stage 1: <title>",
  "role": "implementation",
  "mode": "wait",
  "timeoutMs": 60000,
  "isolation": "shared",
  "target": {
    "providerInstanceId": "codex",
    "model": "gpt-6-sol",
    "options": {"reasoningEffort": "medium"}
  },
  "task": "Build Stage 1 only. Repo: <absolute root>. Read project instructions and <absolute skill directory>/references/stage-executor.md. Plan: <absolute plan path>. Read Shared context lines <a>-<b> and Stage 1 spec lines <c>-<d>. Do not delegate. Return changes, checks, deviations and blockers."
}
```

For a mechanical builder, change the model to `gpt-6-luna`. For verification, use Luna, `role: test`, the verifier reference, root and exact commands. Do not pass a stage spec to a command verifier.

- Children receive only the task, not parent history. Include all paths, constraints and relevant prior findings in it, but reference the plan rather than repeating it. Keep the task ID and returned link.
- Inherit runtime permissions; do not request broader access. `mode: wait` is for results needed by this turn, with waits no longer than 60 seconds. A wait timeout does not cancel the task.
- Follow the returned `next`. If completion will wake the parent, give a brief status and end the turn; resume when notified. Do not poll `task_status`, sleep, use native waits, or create watchers/scheduled wakeups.
- A pending question or approval is not completion. Surface it through T3's supported mechanism; do not grant approval on behalf of the user. Do not treat a partial summary as success.
- Cancel an active task with `task_cancel` when replacing it or when it is no longer needed. Never interrupt the child thread as a substitute.
- Every independent review or re-check is a new `delegate_task` with the scope, findings and objections; never send a new review through `t3_thread_send`.
- When mentioning a child to the user, use its returned link verbatim. Do not expose bare thread IDs as links.

## Finish

Claude compares the changed contracts and targeted diffs with the original goal, checking test adequacy and unresolved deviations. Keep this assessment distinct from Luna's command results. Address a discovered defect through a bounded fix stage and re-check the affected behavior; do not call a passing suite proof of correctness.

Report what changed, verification results and limitations, deviations, local commits (if any) and remaining blockers. Provide a ready-to-paste PR title/body when useful, following the repository template. Distinguish checks actually run from checks unavailable or skipped. State that commits remain unpushed and the plan stays untracked. Do not push, publish or open a PR unless requested.
