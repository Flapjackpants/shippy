# Benchmark

Replay recent real commits from the user's repos and compare coding workflows on
**time, cost and code quality**. Each case drops every arm into the same
one-commit snapshot of the commit's parent, then grades the diff against the
commit's own tests. Stdlib Python 3.13 only; results are markdown.

## Arms

| Arm | Provider | Model | Prompt shape |
|---|---|---|---|
| `oracle` | - | - | Applies the real commit minus its tests; the correctness control |
| `null` | - | - | No change at all; the false-positive control |
| `claude-base` | claudeAgent | `claude-opus-5-5` | Two turns: task + plan-only, then build + commit |
| `codex-base` | codex | `gpt-6-astra` | Two turns: task + plan-only, then build + commit |
| `shippy` | claudeAgent | `claude-opus-5-5` | One turn: `$shippy <task>` |
| `shippy-t3` | claudeAgent | `claude-opus-5-5` | One turn: `$shippy-t3 <task>` |

Every agent turn ends with a no-human clause: treat the plan as approved, never
ask, take the recommended option, do not push. `shippy` and `shippy-t3` run the
**installed** skill copies under `~/.claude/skills/`.

## Cases

Repos live in `~/Documents/programming/personal/`.

| Case | Repo | Commit | Size | Language |
|---|---|---|---|---|
| `captain-retakes` | captain | `043e883` | small | python |
| `captain-silence-trim` | captain | `93bf999` | medium | python |
| `rightnow-referral` | rightnow-ai | `2c4faa3` | medium | typescript |
| `rightnow-slack` | rightnow-ai | `8debc42` | large | typescript |
| `ht-indexer-retry` | Historical_Textures | `03a9666` | small | java |
| `stacksquing-groups` | stackSquing | `3e0230f` | medium | java |

## Method

1. **Snapshot.** `git archive <commit>^` is extracted into a fresh directory, then
   `git init` and one commit `benchmark base` by `bench <bench@localhost>`. The
   workspace has no refs to the source repo and no future history, so the agent
   cannot read the answer from git.
2. **Setup.** Each case's `setup` shell commands run in the workspace (deps,
   generated clients); `exclude` paths and `.bench-junit/` go into the
   workspace's `.git/info/exclude`.
3. **Hidden tests.** The commit's test files are copied in only at grading time,
   never while the agent works.
4. **Controls.** A run is only meaningful when `oracle` resolves and `null` does
   not; `preflight` and the control run check the cases themselves, not models.
5. **Grading, in order:** hygiene, diff (untracked included), hidden tests,
   suite. `resolved = tests > 0 and failures + errors == 0`.
6. **Waits.** A t3 exit 2 (permission prompt) is answered with "No human is
   available; proceed with your recommendation." at most twice, then the run is
   recorded `needs_input`.

## Metrics

| Metric | Source |
|---|---|
| Time | Runner wall clock in seconds; agent arms sum their t3 call durations |
| Cost | Transcript tokens x `prices.json` list price; free workers count $0 |
| Tokens | Claude transcripts (dedupe by message id) + Codex rollouts per workspace |
| Resolved | Hidden test run is green |
| Hidden pass | Passed / runnable hidden tests |
| Suite green | The repo's own suite still passes |
| Judge | Blind `claude-sonnet-5-5` rubric 1-5 per axis and 1-10 overall, on both patches capped at 150 KB |
| Diff | Files, added and deleted lines vs base |
| Hygiene | Conventional subjects, no attribution lines, no uncommitted paths |
| Questions | Permission waits the arm needed |

Judge cost is recorded separately from the arm's cost. A model with no price in
`prices.json` sets `cost_complete=false` and is not counted toward the cost cap.

## Statistics

Paired per case against `claude-base`: for each case take the median over k, then
count wins/losses/ties (lower cost and wall are wins; higher resolved and judge
are wins; a missing value skips that case). Cases with an errored record on
either side are excluded. Medians and sign counts only; draw no conclusion
before k >= 3 on the full set.

## Ladder

1. Controls on all cases: oracle resolved, null unresolved.
2. One case, every agent arm, k=1: sanity of the driver and costs.
3. Three to five cases, k=1: direction only.
4. Full set, k=3: the first result worth a decision-log entry.

## Commands

```sh
python3 benchmarks/bench.py preflight
python3 benchmarks/bench.py run --cases all --arms oracle,null --run-id controls
python3 benchmarks/bench.py run --cases captain-retakes --arms claude-base,codex-base,shippy,shippy-t3 --runs 1 --max-cost-usd 40 --run-id ladder1
python3 benchmarks/bench.py report ladder1
```

`run` writes `benchmarks/results/<run_id>/<case>__<arm>__<k>/record.json` and
`meta.json` (versions, prices, skill hashes); `report` writes `report.md` next to
them. `--no-judge` skips the judge, `--keep-workspace` keeps a control
workspace, `--timeout-min` caps an agent run. Agent arms require
`--max-cost-usd`; the runner stops with exit 2 once spent arm + judge cost
reaches the cap.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `SHIPPY_BENCH_ROOT` | `~/shippy-bench` | Control workspaces and per-slot agent workspaces |
| `SHIPPY_BENCH_RESULTS` | `benchmarks/results` | Records and reports (gitignored) |
| `SHIPPY_BENCH_T3` | `~/.t3/bin/t3`, else PATH | t3 CLI used for agent arms |
| `SHIPPY_BENCH_CLAUDE` | `claude` | Claude CLI used by the judge |
| `SHIPPY_BENCH_CLAUDE_DIR` | `~/.claude/projects` | Claude transcripts for token counts |
| `SHIPPY_BENCH_CODEX_DIR` | `~/.codex/sessions` | Codex rollouts for token counts |

## Adding a case

Add `benchmarks/cases/<id>.json` with `id, repo, commit, size, language, task,
hidden_tests[], setup[], exclude[], test_command, junit_globs[], timeout_min`
(and optional `suite_command`). The commands must write JUnit XML matching
`junit_globs`. Write `task` from the commit message, diff and tests: 80-250
words, name every module, public symbol, signature and error behavior the tests
touch, never include implementation or test code, and end with "Add or update
tests for the new behavior." Then run `preflight` and an `oracle,null` run: the
case is usable only when oracle is resolved and null is not.

## Limitations

- The t3 CLI cannot set effort or runtime mode, so provider defaults apply.
- Free T3 worker tokens are unmetered and counted as $0.
- GPT-6 prices are null, so Codex reports tokens only and is not counted toward
  `--max-cost-usd`.
- `shippy` and `shippy-t3` run the installed copies; `preflight` warns when they
  differ from the repo.
- The captain cases symlink the source repo's `.venv`.
- T3 title-generation calls are not counted.
- T3 projects persist, one per slot under `~/shippy-bench/slots`; remove them in
  T3 when done.
- A timeout leaves the thread running in T3.
- The judge is one LLM and its scores are advisory.
