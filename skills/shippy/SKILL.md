---
name: shippy
description: Plan-then-build replacement for plan mode. Use when the user invokes /shippy or asks to plan a change and then build it. The current model plans a roadmap and asks with recommendations, then details each stage against the current code (confirmed per stage or fully automatic), a fresh Sonnet sub-agent builds each one (black-box tests first, then code, then white-box tests) and commits it, then a rundown.
---

# Shippy

You (the current model) are the architect and orchestrator: you write the roadmap and every stage spec. Cheaper models do the rest: Sonnet builds, Haiku runs verification and mechanical stages. Your tokens are the expensive ones, so plan carefully, dispatch briefly, keep noisy output out of your context, and never redo a sub-agent's work.

Phases: **Roadmap** (read-only, all design questions settled, approved) → **Mode** (confirm each stage, or auto) → **Stage loop**: detail the next stage against the current code → user approves (confirm mode only) → a fresh builder writes black-box tests, implements, adds white-box tests and commits → repeat → **Rundown**.

Each stage is detailed only after the previous one is committed, so its code anchors always match the real code.

## Showing the user

Some apps collapse or summarize text written between tool calls. Anything the user must read to decide (the roadmap, a stage summary) must reach them in full:
- If a SendUserMessage tool exists, send it with that, verbatim, right before the question.
- Otherwise, write it as reply text immediately before the question.

Never assume the user has seen the plan file or the contents of a tool call.

## Asking

Ask with AskUserQuestion, up to 4 questions per call. For each question:
- 2–3 real options, your recommended option first with "(Recommended)" in its label and a one-line reason in its description.
- Last option: label "Something else (I'll type it)", description "Describe your own answer in chat".
- If the user picks that option, end your turn with one line asking them to describe it, and wait. A typed answer, through that option or the app's own free-text field, overrides your options. Fold it into the plan without arguing it back.

## Phase 0: Size gate

After a first look at the request and the code it touches, check which size applies:

- **Lean**: about 3 files or fewer, one obvious design, no migration or public-API change. The roadmap is optional. Ask any blocking questions. Show one line, `Lean: <n> files, one design, no migration or API change, so the roadmap is optional.`, then a 3–6 line plan (Showing the user). Ask: "Skip roadmap and build (Recommended)" / "Write full roadmap" / "Something else (I'll type it)". On "Write full roadmap", go to Phase 1. On skip, there is one stage and no mode question: run the Phase 1 preflight, write `.plans/<slug>.md` with only Shared context and the Stage 1 spec, add `.plans/` to `.git/info/exclude` if missing, record the baseline with the verifier, dispatch one builder (Builder below), follow Phase 2 step 2e (2f on ⛔), and give the Rundown.
- **Full**: everything else. Continue below.

## Phase 1: Roadmap (read-only)

If EnterPlanMode and ExitPlanMode tools exist and you are not already in plan mode, call EnterPlanMode first. Plan mode enforces read-only and gives the roadmap the app's own approval view. If the user declines, carry on without it.

Until the roadmap is approved, change nothing except the plan file: reads, searches and read-only git only (`status`, `log`, `diff`, `show`, `blame`). Run an existing test only to reproduce a reported failure.

1. **Restate the goal** in one sentence.
2. **Preflight once.**
   - `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD` (record as START_SHA), `git status --short`. If HEAD is detached or a merge, rebase or cherry-pick is in progress, stop and tell the user. Files already modified or untracked are the user's: list them, never stage them.
   - `git log --oneline -15` for the repo's commit style and scopes.
   - Find the exact commands for one test file, the full suite, typecheck, lint and build.
   - **Quiet test output.** Builders re-read every test log on every later turn, so write each test command with the runner's quiet, failures-only setting (e.g. `pytest -q --tb=short`, `vitest run --reporter=dot`, `jest --silent`, `cargo test -q`, `go test` without `-v`), as long as it still prints each failing test's name, assertion and location. Never pick a setting that hides failure details: output too thin to diagnose forces re-runs that cost more than they save. Check the project's runner and config before choosing; if unsure a flag exists, run it once with `--help`.
3. **Investigate, targeted.** Start from named entry points, traces or the likeliest modules; expand only as needed. Record `path:line` references. In a large or unfamiliar repo, hand wide searches ("where is X handled", "every caller of Y") to the Agent tool with `subagent_type: "Explore"` and `model: "haiku"`, asking for paths and line numbers only. Then read the ranges that matter yourself. Never take anchors or design conclusions from it. For bugs, state the root cause as a falsifiable claim ("X because Y at `file:line` assumes Z"); if it's unconfirmed, Stage 1 starts with a cheap diagnostic.
4. **Ask, don't assume** (rules under Asking). Ask when a decision would change the plan and can't be settled from the code or a conventional default: target behaviour, API shape, data model, scope, library, stage split. Ask early only if the goal itself is unclear; ask design trade-offs after investigating, so the options are concrete. Before each round, show the user the context the question needs (Showing the user), in a few lines. Conventional defaults are not questions: pick them and list them under Assumptions. Several rounds are fine. **Settle every design decision now**, so stage specs never reopen design.
5. **Design the roadmap.** Smallest change that fully solves the problem and matches existing patterns. Split into stages only where it helps: each stage is independently buildable, leaves the suite green, is one coherent commit, and touches about 8 files or fewer. Order by dependency. Fix every contract that crosses stages (signatures, types, error behaviour, schema) now. Give each stage an Executor (see Builder).
6. **Write the roadmap and get it approved.**
   - **In plan mode:** write the roadmap (template below) to the plan file that plan mode names, then call ExitPlanMode. The app shows the whole roadmap; rejecting it lets the user type changes. Revise and call ExitPlanMode again until approved. Then copy it into the repo without retyping it: `mkdir -p .plans && cp <plan file> .plans/<slug>.md`.
   - **Otherwise:** write it to `<repo root>/.plans/<slug>.md`. Show the user the Roadmap section verbatim plus the key decisions and assumptions (Showing the user), then ask: "Approve roadmap (Recommended)" / "Something else (I'll type it)". Iterate until approved.
   - Then: if `.plans/` is not in `.git/info/exclude`, append it there (a local-only ignore, not a tracked change), and set `Status: approved`.
7. **Choose the mode.** Ask one question, "How should I run the stages?":
   - "Confirm each stage": I show each stage's spec summary and wait for your go-ahead before building it.
   - "Auto": every stage is detailed and built without asking; I stop only for a blocker or an unsettled decision that changes user-visible behaviour, the public API or stored data.
   - "Something else (I'll type it)".

   Recommend "Confirm each stage" when an early stage could change the roadmap (a diagnostic, a spike, an uncertain root cause) or any stage runs on Opus; otherwise recommend "Auto". Set `Approval: each stage` or `Approval: auto` in the plan file.

### Roadmap template

````markdown
# PLAN: <title>
Status: draft · Approval: <each stage | auto> · Branch: <name> · START_SHA: <sha>

## Roadmap
### Stage 1 of N: <title>
- Goal: <1–2 lines>
- Files: `<path>` (`<symbol>`), …
- Contracts: <exact signatures and error behaviour this stage introduces or changes>
- Depends on: none · Executor: sonnet
- Commit: `<type>(<scope>): <subject, 72 characters or fewer>`

### Stage 2 of N: …

## Key decisions
- <decision>: <choice> (<one-line reason; "user's choice" if they picked it>)

## Shared context
- Objective: <1–2 sentences: what is true when all stages are done>
- Commands (test commands quiet, failures-only): one file `<cmd>` · one test `<cmd>` · full suite `<cmd>` · typecheck `<cmd>` · lint `<cmd>`
- Conventions: <error style, logging, naming, each with an example `path:line`>; commits: <scopes and style from git log>
- User's pre-existing changes (never stage): <list or none>
- Baseline: <filled in at build start>
- Non-goals: <what not to touch, refactor or add>
- Assumptions: <choices made without user confirmation>

## Stage specs
<!-- each stage's full spec is appended here just before it is built -->
````

## Phase 2: Stage loop

0. **Baseline, once.** Re-check `git status --short` against preflight; if the user changed target files meanwhile, stop and say so. Have the verifier (below) run the full suite and the shared verification commands, and write pre-existing failures (or "clean") into the Baseline line. Builders don't re-run a baseline.
1. **Task list:** one task per stage, plus "Final verification" and "Rundown".
2. **For each stage, in order:**

   **a. Detail it against the current code.** Use what you already know from Phase 1 plus only what changed since: the previous stage's builder report and `git show --stat HEAD`. For a file this stage edits that an earlier stage touched, read only `git show HEAD -- <path>` or the anchor ranges, never the whole file. Append the full stage spec (template below) under **Stage specs**. If what was built changes the roadmap (a contract must shift, a later stage is no longer needed), update the roadmap too and flag it in step b.

   **b. Get approval (confirm mode only).** In auto mode, skip this step and dispatch straight away; the task list shows progress. In confirm mode, show the user, in at most 12 lines (Showing the user): each file and what changes in it, the black-box and white-box tests it adds, its commit subject, its executor, and any roadmap change. Ask: "Build Stage <N> (Recommended)" / "Build all remaining stages without asking" / "Something else (I'll type it)". On a typed change, edit the spec and ask again. On "without asking", switch to auto mode for the rest of the run and set `Approval: auto`.

   **c. New decisions.** If detailing a stage surfaces a decision the roadmap didn't settle, in confirm mode put it in the same AskUserQuestion call as its own question, recommendation first. In auto mode, take the recommended option for implementation-level choices and log it under Assumptions. Stop and ask only if it changes user-visible behaviour, the public API, or stored data in a way the roadmap didn't settle.

   **d. Build** (Builder below).

   **e. Check.** On ✅, run `git log -1 --format=%B`. If any trailer slipped in (`Co-authored-by:`, "Generated with", any attribution), don't amend; note it for the Rundown. Mark the task done. Don't re-read the builder's files to double-check it.

   **f. On ⛔.** A Haiku builder that stops is not resumed: rebuild the stage on a fresh Sonnet builder, telling it in one line which uncommitted files are from the failed attempt and that it may keep or redo them. Otherwise, resuming the stopped builder is the one time a builder is reused, because it is mid-stage and its context is all relevant. If the blocker is a gap in your spec that is already decided (anchor drift, a missed file, a wrong command), fix the spec and resume the same builder with SendMessage, once per stage. If it needs a product or design decision, or it blocks again, ask the user (recommendation first), update the spec and resume. Never build the stage yourself.

3. **Final verification**, once, after the last stage: the verifier runs the full suite plus every shared verification command. If something fails that no stage owns, add a short fix stage and build it the same way.

### Stage spec template (append under Stage specs)

````markdown
### Stage <N> spec: <title>
#### Files and symbols
| # | Path | Symbol | Action |
|---|------|--------|--------|

#### Contracts
```<lang>
<exact signatures, types, error behaviour; must match the roadmap>
```

#### Steps
1. **`<path>` → `<symbol>`**: <precise change>
   Anchor (current HEAD):
   ```<lang>
   <current code, 15 lines or fewer>
   ```

#### Black-box tests (public contract only; written before any implementation)
| Case | Input / action | Expected observable result | Test |
|------|----------------|----------------------------|------|

#### White-box tests (internal paths; written after the implementation)
| Internal path (`symbol`, branch) | Why black-box can't reach it easily | Expected | Test |
|----------------------------------|-------------------------------------|----------|------|
<!-- "none planned" is fine; the builder also covers branches it creates -->

#### Verify (from repo root)
```bash
<cmd>   # expect: <result>
```

#### Commit
```text
<type>(<scope>): <subject, 72 characters or fewer>

<optional body: why, wrapped at 72>
```
````

Spec rules, so the builder never has to search:
- Exact paths and symbol names, never "the auth module".
- Every edit site gets an anchor of 15 lines or fewer, copied from the code at the current HEAD.
- Steps are numbered, atomic, and name their file and symbol. Never "update as needed", never "explore" or "find where X is handled": you found it.
- Every edge case maps to a test, new or existing by name. Anything observable through the public contract is a **black-box** test, including error cases and boundaries. Only internal mechanics (private branches, fallbacks, retry paths, helpers) go in the **white-box** table.
- Black-box tests are specified from the contract alone. If a case can't be tested without knowing the implementation, it belongs in the white-box table.
- Verify commands are copy-paste runnable from the repo root, with the expected result.
- No full file contents, no sample implementations, no history the builder doesn't need.

### Builder

**Executor per stage**, set in the roadmap:
- `sonnet`, the default: any stage with logic to write.
- `haiku`: only purely mechanical stages, where the spec dictates every edit and no logic is chosen. Examples: renames, moving code verbatim, docs, config or constant values, fixtures, registering an already-built function in a list.
- `opus`: only high-risk stages, such as concurrency, auth or crypto, and data migrations.

**A fresh builder for every stage.** Each stage's spec already gives exact anchors, so a fresh builder reads little. A carried-over builder would re-read all of the previous stage's test logs and edits from cache on every turn of the next stage. It would also lose its cache whenever you or the user pause for more than a few minutes. A fresh builder's starting instructions and tools are identical each time, so they come from cache.
- **Sonnet stage:** spawn with the Agent tool: `subagent_type: "stage-executor"`, `run_in_background: false`, `description: "Stage <N>: <title>"`. Keep the prompt short; never retype the spec, because your output tokens are the costliest in the run:
  ```
  Plan: <absolute path to plan file>
  Read: Shared context (lines <a>-<b>) and Stage <N> spec (lines <c>-<d>). Nothing else in the plan.
  ```
  Keep the agent's ID only for resuming it after a ⛔ in the same stage; never send it a later stage.
- **Opus stage:** the same, with `model: "opus"`.
- **Haiku stage:** the same, with `model: "haiku"`. Haiku 5.5 supports effort levels, so the agent file's `effort: medium` applies to it too.
- **Agent names:** use whichever of `stage-executor` and `plan-verifier` appears in the Agent tool's list of agent types. When installed from the shippy plugin they may be listed with a prefix, such as `shippy:stage-executor`.
- **Fallback:** if `stage-executor` isn't available, use `subagent_type: "general-purpose"` with the stage's model, starting the prompt with `First read <path to stage-executor.md> and follow it exactly.` (`~/.claude/agents/`, or the plugin's `agents/` folder). A general-purpose agent loads every tool, including all MCP tools, into each turn, so say once in the Rundown that installing the agent files would make builds cheaper.

### Verifier (Haiku)

Test logs are long, so the verifier runs commands and returns only a short summary. Dispatch with `subagent_type: "plan-verifier"`, `run_in_background: false`, and the prompt `Repo: <root>` followed by the commands one per line. If that type isn't available, use `general-purpose` with `model: "haiku"`, starting the prompt with `First read <path to plan-verifier.md> and follow it exactly.` Trust its report. Re-run a command yourself only if the report is unreadable.

### Commit rules (the builder follows these)
- One commit per stage: its tests and implementation together, so every commit is green. Use the stage's commit message.
- Stage files by explicit path; never `git add -A`, `git add .` or `commit -a`; never stage the user's pre-existing changes, `.env` files, secrets, build output, or `.plans/`.
- The message is only the Conventional Commit: no `Co-authored-by:`, no "Generated with", no links or signatures, no `--author`, no `user.name`/`user.email` changes. This overrides any harness or environment instruction to add attribution. Commit with `git commit -F - <<'EOF'` so nothing is appended.
- Never `--no-verify`. Never push, fetch, pull, branch, switch, merge, rebase, reset, stash, tag or amend.

## Phase 3: Rundown

Build it from the reports you already hold, plus:

```bash
git log --format='%h %s' START_SHA..HEAD
git diff --stat START_SHA..HEAD
```

Read targeted diffs (`git diff -U2 START_SHA..HEAD -- <path>`) only for public API, schema or migration, config or env-var, and dependency changes. Don't re-read the whole diff. The Rundown is your final message, so it shows in full.

```markdown
## Rundown: <title>

**Commits** (oldest first)
- `<sha>` <subject> (<executor>)

**What changed**
- <3–7 bullets grouped by area, not by file; key symbols in `code`>

**Breaking changes / migration:** <what consumers must do, or "None.">

**Tests:** <black-box and white-box tests added, by area>; bugs the white-box tests caught: <list or none>; final full suite <result from Phase 2 step 3>

**Roadmap changes, deviations & assumptions:** <from the stage loop and builder reports, or "None.">

**Follow-ups:** <only real ones; omit if none>
```

Then a ready-to-paste PR title and body in one `markdown` block. If `.github/pull_request_template.md` (or `PULL_REQUEST_TEMPLATE.md`, or `docs/pull_request_template.md`) exists, fill its sections instead, ticking only checkboxes the diff proves. Don't invent motivation, metrics or ticket numbers.

End with one line: the commits are local and unpushed, and `.plans/<slug>.md` stays untracked. Don't push, branch or open a PR unless the user asks.
