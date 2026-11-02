---
name: shippy-chatgpt
description: Plan and build a code change in stages using Astra as orchestrator and fresh Luna agents at medium reasoning for implementation and verification. Use when the user requests the ChatGPT version of shippy or invokes $shippy-chatgpt.
---

# Shippy for ChatGPT / Codex

Astra investigates, designs the roadmap and writes each stage spec. Fresh Luna agents build individual stages and run verification, returning compact evidence. This port is unbenchmarked; do not promise token savings or equivalent quality.

## Runtime and model contract

- Orchestrator: the current session, preferably `gpt-6-astra`. A skill cannot change its own session model. If the session uses another model, disclose it and honor the user's choice before claiming an Astra run.
- Builders and verifier: `gpt-6-luna`, reasoning effort `medium`, including mechanical and high-risk stages. Do not silently escalate models. For high-risk work, make stages smaller and contracts more explicit; request a model change only if necessary to resolve a blocker.
- Requires repository read/write access, command execution and a subagent tool that supports the requested model and reasoning. Check actual capabilities before starting. If missing, explain what is unavailable; do not pretend a prompt creates agents or changes their models.
- Explicitly delegate each implementation stage and baseline/final verification. Run stages sequentially in the shared checkout; never run two writers together. Children must not delegate.
- Use the host's supported dispatch route. For native `collaboration.spawn_agent`, use the example below. If host instructions require an orchestration service for explicit model settings, use that service's capability discovery and lifecycle instead; do not guess its schema or switch routes after an unavailable-model error.
- Read [references/stage-executor.md](references/stage-executor.md) when preparing a builder and [references/plan-verifier.md](references/plan-verifier.md) when preparing verification. Resolve their absolute paths before dispatch.

## Planning and authorization

1. Read project instructions, inspect git status and record branch and `START_SHA`. Preserve existing edits and staged files. Stop for an in-progress merge/rebase/cherry-pick or detached HEAD before making commits.
2. Investigate relevant code, existing tests and exact verification commands. Prefer targeted searches. Use quiet test flags only when supported and failure details remain visible. State a falsifiable root cause for bugs; if uncertain, make the first stage diagnostic.
3. Use one stage for a small, obvious change (roughly three files, no migration or API change). Otherwise write a roadmap with dependency-ordered stages, each independently verifiable and roughly eight files or fewer. Set shared signatures, error behavior and schema contracts before building.
4. Clarify only material decisions that code and conventional defaults cannot settle. Use the host's question tool when available, recommended choice first, preserving free-text answers. Never invent Claude's `AskUserQuestion` or plan-mode tools.
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
   - Commit policy and exact Conventional Commit message if applicable.
   Do not include full files or sample implementations. Docs and mechanical changes may use inspection instead of artificial tests.
4. Honor any requested stage gate. Show the files, behavior, checks and executor before asking. Otherwise dispatch immediately with the plan ranges and executor reference; never copy the entire conversation to a builder.
5. Wait for the builder using the host's supported lifecycle. With native tools, wait for its final response, not just a progress message. With an orchestration service, follow its returned continuation instructions; do not poll or substitute native waits. Do not start the next stage while a writer remains active.
6. Inspect the report and targeted evidence: status, diff stat and commit identity when applicable. Investigate missing checks, unexpected files or contract deviations; do not routinely reread all code or rerun passing commands.
7. If blocked, fix a spec/anchor/command gap and resume the same builder when supported, once per stage. If resume is unavailable, dispatch a fresh builder identifying partial edits it owns. For a second blocker or a new product decision, return the concrete blocker to the user. Never retry indefinitely or change model silently.
8. After the last stage, run final verification via a fresh Luna verifier. A new failure gets a bounded fix stage; environmental blockers must remain explicitly reported, not labeled passing.

### Native dispatch example

Use this only when the host exposes this schema and allows native dispatch for these settings:

```javascript
collaboration.spawn_agent({
  task_name: "stage_1",
  model: "gpt-6-luna",
  reasoning_effort: "medium",
  fork_turns: "none",
  message: "Build Stage 1 only. Repo: <absolute root>. Read project instructions and <absolute skill directory>/references/stage-executor.md. Plan: <absolute plan path>. Read Shared context lines <a>-<b> and Stage 1 spec lines <c>-<d>. Do not delegate."
})
```

Use a unique task name per stage and fresh verification run. `fork_turns: "none"` avoids inherited orchestration history and allows explicit model/effort overrides. The prompt must supply every needed path and constraint. For verification, use the same model/effort, point to `references/plan-verifier.md`, and supply the repository root and exact commands.

## Finish

Report what changed, verification results and limitations, deviations, local commits (if any) and remaining blockers. Provide a ready-to-paste PR title/body when useful, following the repository template. Distinguish checks actually run from checks unavailable or skipped. State that commits remain unpushed and the plan stays untracked. Do not push, publish or open a PR unless requested.
