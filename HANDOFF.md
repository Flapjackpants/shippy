# HANDOFF: shippy (formerly plan-ship)

**Read this first.** It carries everything from the conversation where shippy was designed: what it is, why each decision was made, what's still unverified, what the research found, and how to benchmark it. Nothing else from that conversation is needed.

Status as of 2026-11-01: v0.4.0. Designed and written, never benchmarked or run end to end.

---

## 1. Goal

shippy is a Claude Code skill that replaces the built-in plan mode with a plan-then-build pipeline that is **cheaper per unit of working code**:

1. The session model (normally Opus) investigates read-only, asks the user questions with recommendations, and writes a staged roadmap.
2. Each stage is detailed into a precise spec just before it's built, then built by a cheaper sub-agent: Sonnet by default, Haiku for mechanical stages, Opus for risky ones.
3. Each stage is built in a fixed order: black-box tests, then the implementation, then white-box tests. Then it is verified and committed as one Conventional Commit.
4. A rundown and a ready-to-paste PR description at the end.

It merges four earlier skills by the same user: `plan-architect`, `plan-executor`, `commit-as-you-go` and `pr-standup`. Their ideas are folded in; shippy doesn't load them.

**The project's next job:** prove with benchmarks that shippy is cheaper than default Claude Code with no worse quality, then tune it using measurements instead of guesses.

## 2. Repo layout

```
.claude-plugin/plugin.json      plugin manifest (name: shippy)
.claude-plugin/marketplace.json marketplace entry, for `claude plugin install`
README.md                       overview and install commands
skills/shippy/SKILL.md          the orchestrator skill (~2,960 words)
agents/stage-executor.md        builder agent: model sonnet, effort medium, 6 tools
agents/plan-verifier.md         verifier agent: model haiku, Bash only
HANDOFF.md                      this file
CLAUDE.md                       working rules for agents in this repo
.gitignore                      evals/results/, .plans/
```

**Install for use:**
- **Plugin:** load this directory as a plugin, which should register the skill and both agents.
- **Manual:** copy the two agent files to `~/.claude/agents/` and upload the skill.

**State of the user's account (clean up):**
- An old `plan-ship-auto` skill may still be installed. It was merged into shippy, so delete it.
- `stage-executor` was mistakenly installed as a *skill*. It only works as an agent, so delete the skill copy.

## 3. How shippy works (summary; SKILL.md is authoritative)

- **Size gate:** changes touching about 3 files or fewer, with one obvious design and no migration or public-API change, run in **Lean** mode: no plan file and no sub-agents. The session model asks, shows a short plan, gets approval, builds in the same test order, and makes one commit. Everything else runs in **Full** mode.
- **Phase 1, Roadmap (read-only):**
  - Enters native plan mode if `EnterPlanMode`/`ExitPlanMode` exist, which enforces read-only and gives the app's own plan approval view.
  - Preflight runs once: branch, START_SHA, the user's pre-existing changes, commit style, and test commands with **quiet, failures-only output**.
  - Investigation is targeted. Wide searches in big repos go to an Explore agent on Haiku, which returns paths and lines only.
  - **Every design question is settled here**, with AskUserQuestion: recommended option first, plus a "Something else (I'll type it)" option.
  - Writes the roadmap: per stage, a goal, files, the contracts that cross stages, an executor and a commit subject. It goes to `.plans/<slug>.md`, kept out of git through `.git/info/exclude`.
  - Asks for **mode**: confirm each stage, or auto.
- **Phase 2, Stage loop:**
  - Baseline runs once, through the Haiku verifier.
  - For each stage, the session model writes the full spec **just in time**, with code anchors taken from the current HEAD. It reads only the previous stage's report and `git show` output for files it already knows.
  - In confirm mode, it shows a summary of up to 12 lines and asks before building.
  - A **fresh** builder runs each stage. Its dispatch prompt is two lines, pointing at line ranges in the plan file; the spec is never retyped.
  - On ✅ it checks the commit message for attribution trailers. On ⛔ it resumes the same builder only within the same stage. A Haiku builder that stops is redone on Sonnet.
  - Final verification runs once, through the verifier.
- **Phase 3, Rundown:** built from the builder reports, `git log` and `git diff --stat`, plus targeted diffs for API, schema, config and dependency changes. Ends with a PR body and nothing is pushed.

## 4. Decision log (why things are the way they are)

| # | Decision | Reason | Rejected alternative |
|---|---|---|---|
| D1 | Session model writes all plans and specs; sub-agents only build, verify or search | Spec quality drives everything downstream, and planning needs the user's questions answered first-hand | A cheaper orchestrator with Opus as a planning sub-agent. Sub-agents can't spawn sub-agents, so the cheap model would have to own the main thread, Opus's questions would reach the user second-hand, and two contexts would grow instead of one. Orchestration itself is a small fraction of main-thread tokens. |
| D2 | Roadmap up front, specs **just in time** per stage | Anchors written up front go stale ("drift") when earlier stages edit the same files | Writing every stage spec up front (the v0.1 design) |
| D3 | All design decisions settled in the roadmap | Just-in-time specs must not reopen design, especially in auto mode | — |
| D4 | One skill with a mode question after roadmap approval | The user preferred this over two skills; confirm mode can also switch to auto mid-run | A separate `plan-ship-auto` skill (built, then merged) |
| D5 | **Fresh builder per stage** | Cache maths (§5): carried context is mostly noise and is re-read every turn; a pause of more than 5 minutes expires the cache; a fresh builder's prefix is cache-identical | One builder continued across stages (v0.2–0.3). Reversed after the cost analysis. |
| D6 | Black-box tests → implementation → white-box tests, in one builder | The user required it. Black-box tests come from the contract alone and must fail first. White-box tests cover internal branches afterwards and assert intended behaviour, so a failure means a real bug. | Splitting test writing and implementation across agents: the implementer would have to re-read all the tests and failures, so it costs more. |
| D7 | No parallel builders | They do the same total work, cost the same or more, collide in one working tree, and isolated worktrees create branches, which the user's rules reserve for the user | GSD-style parallel waves |
| D8 | Executor per stage: sonnet (default), haiku (purely mechanical only), opus (concurrency, auth/crypto, migrations) | Match model cost to risk | — |
| D9 | Haiku verifier for baseline and final runs | Keeps long test logs out of the expensive session model's context | The session model running test suites itself |
| D10 | Quiet, failures-only test commands chosen at preflight (v0.4) | Test output is the builder's biggest re-read cost. This gets most of rtk's benefit without its command-rewriting hook (see §6) | Installing rtk |
| D11 | Haiku stages use the `stage-executor` agent with a model override (v0.4) | The model docs say Haiku 5.5 supports effort levels; a general-purpose agent loads every tool, including MCP tools, every turn | general-purpose plus "read the agent file" (v0.3 workaround) |
| D12 | Dispatch prompt = plan path + line ranges, never the spec text | The session model's output tokens are the most expensive in the run | Superpowers pastes the full task text into each sub-agent |
| D13 | Plan file kept out of git with `.git/info/exclude` | Never committed, and no change to the tracked `.gitignore` | — |
| D14 | Show the roadmap and stage summaries with SendUserMessage, or as reply text right before the question | Some apps collapse text written between tool calls; the user reported the plan being hidden | — |
| D15 | Explicit "Something else (I'll type it)" option on every question | AskUserQuestion is supposed to offer "Other" on its own, but the user didn't see it | — |
| D16 | Not adopted: Caveman, Ponytail, rtk, `opusplan` | See §6. Caveman's brevity rules are already in shippy. Ponytail's minimalism belongs at design time. rtk raised cost in tests. `opusplan` would put stage specs on Sonnet, because they're written outside plan mode. | — |
| D17 | Commits: one per stage, explicit-path staging, Conventional Commits, **no Co-authored-by or any AI attribution**, never push, branch, merge, rebase, reset, stash, tag or amend, never `--no-verify` | The user's standing rules from commit-as-you-go | — |

**Open idea from the research (not adopted):** add Ponytail's minimalism checklist to the design step. Before writing any contract, check whether existing code, the standard library, a platform feature or a current dependency already covers it, and never trim validation, error handling, security or accessibility. Offered but not yet applied. Benchmark it as an experiment (§8.6).

## 5. Token economics model (the basis for D5, D9, D10, D12)

- **Approximate list prices, Sonnet 5.5** (verify on the current Anthropic pricing page): input $3/M, output $15/M; cache write ~1.25× input with the 5-minute TTL (~2× with the 1-hour TTL); cache read ~0.1× input.
- **Every tool call is a turn, and every turn re-reads the whole context.** A sub-agent's cost is dominated by cache reads of its growing context, roughly 0.1 × context size, summed over its turns.
- **Carry-over versus fresh** (worked example: a 25-turn stage, 50k tokens carried over of which about 10k are useful):
  - Carrying over: 50k × 25 × 0.1 ≈ 125k token-equivalents ≈ $0.38.
  - Fresh: re-caching 10k at 1.25×, then 10k × 25 × 0.1 ≈ 37.5k ≈ $0.11.
  - Rough break-even: carrying over wins only when carried noise is less than about 12.5 × useful re-read ÷ turns. In practice that means only short, clean stages followed immediately by a stage on the same files.
- **Cache expiry:** with the 5-minute TTL, any pause (the user reviewing a stage, the session model writing the next spec) means re-caching the whole carried context.
- **Output tokens are a small share of a Claude Code bill** (1–3% by one estimate), so prose-shortening tools barely move cost. Input and cache reads dominate (cache traffic was about 80% of one measured bill).
- **Implication:** the levers are shrinking what each agent carries and re-reads (test output, tool definitions, irrelevant history) and keeping prefixes stable for caching.

## 6. Research findings

| Tool | What it does | Lesson for shippy |
|---|---|---|
| **Superpowers** (obra) | Fresh sub-agent per task, test-first, then two reviewer sub-agents per task (spec compliance, then code quality), each looping until approval; the controller pastes the full task text | Says itself that it "costs more". Possible experiment: one cheap spec-compliance reviewer on `opus`-flagged stages only. |
| **GSD** | Discuss → plan → execute → verify; a fresh 200K sub-agent per plan; parallel waves; atomic commits; `--minimal` install cuts startup overhead from ~12K tokens to ~700 | Validates D5. Fixed startup overhead is a real cost, so keep SKILL.md compact. |
| **`opusplan`** (built in) | Opus in plan mode, Sonnet everywhere else | Incompatible with just-in-time specs (D16) |
| **Aider architect/editor** | Planner model plus editor model; even self-pairing raised scores (Sonnet 77.4 → 80.5%) | Evidence that splitting planning from editing helps quality |
| **rtk** | A PreToolUse hook rewrites Bash commands to compress output | JetBrains' paired test (86 SkillsBench tasks, ~425 runs): **+7.6% median cost at low effort** (turns +13.8%, cache reads +14.3%); neutral at high effort; quality tied. Its own dashboard claimed 96M tokens saved. |
| **Caveman** | Terse, telegraphic prose | About 8.5% fewer output tokens; one test found only 4% better than a plain "be concise"; under 1% of the bill |
| **Ponytail** | Climbs a "does this code need to exist?" ladder before writing | About 10% cheaper per task (p=0.004), about 15% less code, quality not significantly different. Only worked when injected as a plugin; copying the SKILL.md never activated it. Savings depend on the agent over-building. |
| **SkillsBench** (paper) | 84–86 tasks, paired runs with no skills, curated skills and self-written skills | Curated skills +16pp on average; skills models wrote for themselves −1.3pp. 2–3 skills is best. Compact or detailed skills help (+17–19pp); "comprehensive" ones hurt (−2.9pp). |
| **Quesma tokenomics** | Survey of cost evidence | Claude Code's fixed setup overhead was about 32.8K tokens versus OpenCode's 6.9K. Load tools on demand; protect the cache (one 38% cut in tool output *raised* total cost by breaking the cached prefix). |

## 7. Unverified assumptions (check these before benchmarking; each could break a run)

1. **`effort:` in agent frontmatter** is accepted, and applies when the Agent tool's `model` override is used (Opus or Haiku stages).
2. **Plugin agent names:** whether plugin agents are listed as `stage-executor` or `shippy:stage-executor`. SKILL.md tells the model to use whichever appears in the list.
3. **Resuming a stopped builder** with SendMessage while keeping its context works for agents dispatched with `run_in_background: false`.
4. **Plan-mode flow:** EnterPlanMode needs the user's consent; ExitPlanMode reads the plan file plan mode names; copying it to `.plans/` with `cp` after approval works; AskUserQuestion works inside plan mode.
5. **The built-in "Other"** free-text field on AskUserQuestion is visible in the user's app. If it is, the explicit "Something else" option is redundant clutter.
6. **The Explore agent** accepts `model: "haiku"`.
7. **Quiet test flags** really keep enough failure detail for each runner, especially `jest --silent`, which hides console output (possibly needed for debugging).
8. **The harness's own attribution:** this environment may automatically add `Co-Authored-By`/session trailers to commits. The user's rule is **no Claude co-author or attribution**, and shippy's commit rules override the harness. The post-commit trailer check exists to catch it. Confirm builders don't add trailers on their own.
9. **Headless runs can't answer AskUserQuestion,** which affects eval design (§8.2).

## 8. Benchmark plan

### 8.1 Harness: `claude plugin eval`

- **Suite layout:** the suite lives in `evals/`, one directory per case, each with `prompt.md`, `graders/*.md` (frontmatter `type`, optional `weight` and `arm`), and an optional `case.yaml` (`schema_version: "1.1"`, `name`, and a `context` block to seed a workspace from a script or fixtures, or continue a saved conversation with `context.history_file`).
- **Getting started:** `claude plugin eval init` drafts cases interactively. Check exact field names against the docs; don't trust this summary for syntax.
- **Baseline:** each case runs with the plugin and with no plugin (default `--runs 3` per side), giving `WITH`, `W/OUT`, `Δ` and a list-price `COST`.
- **Grader types:** `regex`, `tool_used`, `tool_order` and `file_exists` are free; `llm` and `baseline` call a judge model. Skill-fired graders are reported but not scored in a with/without run.
- **Key options:**
  - `--max-cost-usd`: spending ceiling.
  - `--json results.json`: results for trend charts.
  - `--ablation none`: one arm only, for cheap grader iteration.
  - `--judge-model sonnet`.
  - `--allow-tools`: shippy needs Write, Edit, Bash and Agent.
  - `--trust-plugin`: for CI.
- **Pin models in CI** so results stay comparable.

### 8.2 Case design

- **Tasks:** 10–20 multi-stage features or bug fixes from real repos (ideally the user's own), replayed from historical commits, SWE-bench style. Seed the repo at the parent commit; **hold back the real tests** and grade with them.
  - Mix them: about 30% Lean-sized, 50% with 2–3 stages, 20% with 4 or more stages, with at least one stage that should be marked `haiku` and one that should be marked `opus`.
- **No live user in eval runs:** write prompts with complete requirements and an instruction to use auto mode. Alternatively, seed a saved conversation where the roadmap questions are already answered (`context.history_file`). Track "asked a question anyway" as a metric.
- **External check:** SkillsBench (Harbor containers; the dataset is on Hugging Face as `benchflow/skillsbench`). It's mostly data and repair work rather than multi-stage features, so use it for regression checks, not as the main score.

### 8.3 Graders (each case gets a result grader and a process grader)

- **Result:** the prompt asks Claude to run the held-back test command at the end and write the outcome to a file. Grade it with `regex`, and assert the command actually ran with `tool_used` plus `input_match`.
- **Process:**
  - `tool_used: Skill` (shippy fired).
  - `tool_order`: a test file written before the matching source file, for black-box tests first; may need path matching.
  - `tool_used: Agent` (a builder was dispatched in Full mode).
- **Commit hygiene:** run a script after the run that greps `git log` for `Co-authored-by`/`Generated with`, checks Conventional Commit format, and checks out each commit to confirm the suite is green at every commit.

### 8.4 Metrics (decide primary endpoints before paying for runs)

- **Primary:** hidden-test pass rate, and median billed cost per task.
- **Secondary:**
  - cost split by model (Opus, Sonnet, Haiku) and by token type (cache read, cache write, new input, output);
  - turns; wall-clock time;
  - questions asked;
  - ⛔ rate per stage; drift deviations reported;
  - bugs caught by white-box tests;
  - whether every commit is green.
- **Sources:** headless `claude -p --output-format json` (reports total cost, usage and turn count per run); Claude Code's OpenTelemetry export (`CLAUDE_CODE_ENABLE_TELEMETRY=1`, token usage by type and model, and cost). Verify the metric and attribute names against the monitoring-usage docs. Record that the treatment fired: transcripts should show the sub-agents on the intended models.

### 8.5 Method (from JetBrains' rtk and Ponytail studies)

- **Statistics:** compare each task with and without the change (paired); report medians with Wilcoxon signed-rank tests for cost and tokens, and an exact sign test for quality. Never conclude from a single run per task.
- **Ladder:** replay one transcript, then 3–5 tasks with k=1, then with k=3, then the full set.
- **Exclusions:** leave tasks that errored in either arm out of both arms.
- **Effort:** run at two effort levels; rtk's result flipped between low and high.
- **What to trust:** billed cost, never a tool's own savings report.
- **Guardrails:** always set `--max-cost-usd`.

### 8.6 Experiment backlog (one change per experiment, in this order)

| # | Experiment | Hypothesis |
|---|---|---|
| E0 | shippy versus no plugin (default Claude Code) | Lower median cost, pass rate not lower |
| E1 | Quiet versus verbose test commands | Lower builder cache reads; watch for extra turns or re-runs |
| E2 | Builder at low versus medium effort | Low is cheaper per turn but may add turns (watch the rtk effect) |
| E3 | Haiku verifier versus the session model running tests | The verifier lowers session-model input cost |
| E4 | Fresh versus carried builder (re-add the v0.3 carry-over rule behind a flag) | Fresh is cheaper unless stages are short and on the same files |
| E5 | Confirm versus auto mode (simulated approvals) | Auto is cheaper because of cache expiry during pauses |
| E6 | Ponytail checklist in the design step | Smaller specs and less code, quality unchanged |
| E7 | One spec-compliance reviewer on `opus` stages (Superpowers-lite) | Fewer escaped bugs at small cost |
| E8 | Lean threshold of 3 versus 5 files | Find the break-even point for sub-agent overhead |
| E9 | Splitting SKILL.md (moving the Rundown and PR-template rules to a reference file read at the end) | Slightly lower session-model input, no behaviour change |

## 9. Next tasks (suggested order)

1. Run `claude plugin validate .`; fix the manifest and layout. Check how the agents register (§7.2).
2. Smoke test: one small real task in Lean mode and one 2-stage task in Full mode, interactively. Check §7 items 1–8 from the transcripts.
3. Build the eval suite (§8.2–8.3), starting with 3 cases, `--runs 1`, `--ablation none`, to debug the graders cheaply.
4. Run E0 at full size; record the baseline numbers in `benchmarks/RESULTS.md` (create it), with the model IDs, Claude Code version and date.
5. Work through E1–E9, changing one thing at a time and keeping only changes that pass the statistics in §8.5.
6. Keep this file's decision log (§4) current: every adopted or rejected change gets a row and a link to its results.

## 10. Sources

- Claude Code plugin evals: https://code.claude.com/docs/en/plugin-evals
- Claude Code model configuration (`opusplan`, effort levels, Haiku 5.5 effort): https://code.claude.com/docs/en/model-config
- Claude Code monitoring/OpenTelemetry: https://code.claude.com/docs/en/monitoring-usage
- JetBrains, rtk paired benchmark: https://blog.jetbrains.com/ai/2026/07/rtk-claude-code-token-savings/
- JetBrains, Ponytail tested: https://blog.jetbrains.com/ai/2026/07/ponytail-skill-claude-tested/
- Caveman measured savings: https://www.implicator.ai/caveman-claude-code-skill-cuts-output-20-your-bill-barely-notices-2/
- Token-saving plugins summary: https://www.mindstudio.ai/blog/claude-token-saving-plugins-tested/
- Superpowers subagent-driven-development: https://www.mintlify.com/obra/superpowers/skills/subagent-driven-development
- GSD overview: https://www.augmentcode.com/learn/gsd-58k-stars-claude-code
- Aider architect/editor: https://aider.chat/2024/09/26/architect.html
- rtk: https://github.com/rtk-ai/rtk
- Quesma tokenomics: https://quesma.com/tokenomics/
- SkillsBench paper: https://arxiv.org/html/2602.12670v1
