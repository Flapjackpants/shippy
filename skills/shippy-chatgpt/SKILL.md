---
name: shippy-chatgpt
description: Plan and build a code change in stages using Astra as orchestrator and fresh Sol agents at medium reasoning for implementation, and Luna medium for mechanical stages and command verification. Use when the user requests the ChatGPT version of shippy or invokes $shippy-chatgpt.
---

# Shippy for ChatGPT / Codex

Astra investigates, designs the roadmap and writes each stage spec. Fresh Sol agents build ordinary stages; Luna handles mechanical stages and runs verification commands, returning compact evidence. This port is unbenchmarked; do not promise token savings or equivalent quality.

## Runtime and model contract

- Orchestrator: the current session, preferably `gpt-6-astra`. A skill cannot change its own session model. If the session uses another model, disclose it and honor the user's choice before claiming an Astra run.
- Default builder: `gpt-6-sol`, reasoning effort `medium`, for stages with meaningful logic, debugging, interacting components or high-risk behavior. Make high-risk stages smaller and contracts explicit.
- Mechanical builder: `gpt-6-luna`, reasoning effort `medium`, only for tightly specified stages requiring little implementation judgment: renames, docs, config, fixtures or wiring existing functions. A small file count alone does not make a stage mechanical.
- Baseline and final command verifier: `gpt-6-luna`, reasoning effort `medium`. Astra assesses correctness and test adequacy; a passing command report is not an independent code review.
- Preserve exact model generations and effort settings. Do not silently substitute unavailable models or escalate a blocked Luna stage to Sol; obtain agreement unless that escalation is already authorized in the plan.
- Requires repository read/write access, command execution and a subagent tool that supports the requested model and reasoning. Check actual capabilities before starting. If missing, explain what is unavailable; do not pretend a prompt creates agents or changes their models.
- Explicitly delegate each implementation stage and baseline/final verification. Run stages sequentially in the shared checkout; never run two writers together. Children must not delegate.
- Use the host's supported dispatch route. For native `collaboration.spawn_agent`, use the example below. If host instructions require an orchestration service for explicit model settings, use that service's capability discovery and lifecycle instead; do not guess its schema or switch routes after an unavailable-model error.
- Read [references/stage-executor.md](references/stage-executor.md) when preparing a builder and [references/plan-verifier.md](references/plan-verifier.md) when preparing verification. Resolve their absolute paths before dispatch.

## Showing and asking

Some apps collapse text written between tool calls. Anything the user must read to decide (the plan, a stage summary) goes in reply text immediately before the question. Never assume they have seen the plan file or a tool call's contents.

Ask with the host's question tool. Never invent Claude's `AskUserQuestion` or plan-mode tools. Up to 4 questions per call. Each has 2-3 real options: your recommendation first, with "(Recommended)" in its label and a one-line reason, and last "Something else (I'll type it)". A typed answer overrides your options; fold it into the plan without arguing it back. If no question tool exists, ask in reply text in the same format and end the turn.

## Planning and authorization

Until the plan is approved, change nothing except the plan file: reads, searches and read-only git only. Run an existing test only to reproduce a reported failure.

1. Read project instructions, inspect git status and record branch and `START_SHA`. Preserve existing edits and staged files. Stop for an in-progress merge/rebase/cherry-pick or detached HEAD before making commits.
2. Investigate relevant code, existing tests and exact verification commands. Prefer targeted searches. Use quiet test flags only when supported and failure details remain visible. State a falsifiable root cause for bugs; if uncertain, make the first stage diagnostic.
3. Use one stage for a small, obvious change (roughly three files, no migration or API change). Otherwise write a roadmap with dependency-ordered stages, each independently verifiable and roughly eight files or fewer. Set shared signatures, error behavior and schema contracts before building.
4. Ask, don't assume. After investigating, so the options are concrete, ask whenever a decision would change the plan and neither code nor a conventional default settles it: target behavior, API shape, data model, scope, library or stage split. List conventional defaults under Assumptions. Several rounds are fine; settle every design decision before building.
5. Write the plan: commands, conventions, non-goals, existing changes, assumptions, and later the baseline results. With more than one stage, if plan-mode tools are exposed, enter plan mode, write it to the file plan mode names, and copy that file to `.plans/<slug>.md` once approved. Otherwise write `.plans/<slug>.md`. Exclude it locally through the repository's git exclude file if needed, using `git rev-parse --git-path info/exclude` rather than assuming `.git` is a directory. Keep it out of commits.
6. Get the plan approved. A request to implement is not approval, and neither is a missing reply; only an explicit instruction to skip approval waives this gate. For one stage, show a 3-6 line plan and ask "Skip roadmap and build (Recommended)" / "Write full roadmap" / "Something else (I'll type it)". Otherwise request approval through the plan-mode exit tool, or show the roadmap with key decisions and assumptions and ask "Approve roadmap (Recommended)" / "Something else (I'll type it)". Iterate until approved.
7. With more than one stage, ask "How should I run the stages?": "Confirm each stage" (show each stage's summary and wait) / "Auto" (stop only for a blocker or an unsettled decision that changes user-visible behavior, the public API or stored data) / "Something else (I'll type it)". Recommend "Confirm each stage" when an early stage could change the roadmap (a diagnostic, a spike, an uncertain root cause); otherwise recommend "Auto". Record `Approval: each stage | auto | plan only`.
8. Record `Commits: per stage` by default, without asking: one local commit per stage. Use `Commits: none` only when the user or repository rules explicitly forbid commits. That does not prevent building; record stage completion and refresh anchors from the working tree instead.

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
4. In confirm mode, show in at most 12 lines each file and what changes in it, the tests added, the commit subject, the executor and any roadmap change. Ask "Build Stage <N> (Recommended)" / "Build all remaining stages without asking" / "Something else (I'll type it)". On a typed change, edit the spec and ask again; on "without asking", set `Approval: auto`. In auto mode, skip this. A decision the plan did not settle goes in the same question in confirm mode; in auto mode take your recommendation for implementation-level choices and log it under Assumptions, asking only if it changes user-visible behavior, the public API or stored data. Dispatch with the plan ranges and executor reference; never copy the entire conversation to a builder.
5. Wait for the builder using the host's supported lifecycle. With native tools, wait for its final response, not just a progress message. With an orchestration service, follow its returned continuation instructions; do not poll or substitute native waits. Do not start the next stage while a writer remains active.
6. Inspect the report and targeted evidence: status, diff stat and commit identity when applicable. Check `git log -1 --format=%B` for attribution the spec did not supply; remove it as the stage executor's commit policy describes, under the same limits, and report it. Investigate missing checks, unexpected files or contract deviations; do not routinely reread all code or rerun passing commands.
7. If blocked, fix a spec/anchor/command gap and resume the same builder when supported, once per stage. If resume is unavailable, dispatch a fresh builder identifying partial edits it owns. For a second blocker or a new product decision, return the concrete blocker to the user with a recommended resolution. Never retry indefinitely or change model silently.
8. After the last stage, run final verification via a fresh Luna verifier. A new failure gets a bounded fix stage; environmental blockers must remain explicitly reported, not labeled passing.

### Native dispatch example

Use this only when the host exposes this schema and allows native dispatch for these settings:

```javascript
collaboration.spawn_agent({
  task_name: "stage_1",
  model: "gpt-6-sol",
  reasoning_effort: "medium",
  fork_turns: "none",
  message: "Build Stage 1 only. Repo: <absolute root>. Read project instructions and <absolute skill directory>/references/stage-executor.md. Plan: <absolute plan path>. Read Shared context lines <a>-<b> and Stage 1 spec lines <c>-<d>. Do not delegate."
})
```

Use a unique task name per stage and fresh verification run. `fork_turns: "none"` avoids inherited orchestration history and allows explicit model/effort overrides. The prompt must supply every needed path and constraint. For a mechanical builder, change the model to `gpt-6-luna` and keep `medium` effort. For verification, explicitly select `gpt-6-luna` at `medium`, point to `references/plan-verifier.md`, and supply the repository root and exact commands.

## Finish

Astra compares changed contracts and targeted diffs with the original goal, checks test adequacy, and resolves deviations. Keep this assessment distinct from Luna's command results. Address discovered defects through a bounded fix stage and verify the affected behavior.

Report what changed, verification results and limitations, deviations, local commits (if any) and remaining blockers. Provide a ready-to-paste PR title/body when useful, following the repository template. Distinguish checks actually run from checks unavailable or skipped. State that commits remain unpushed and the plan stays untracked. Do not push, publish or open a PR unless requested.
