# shippy

A family of skills for a plan-then-build pipeline: the orchestrator plans, focused agents build, and every agent carries only what it needs. Choose the Claude, ChatGPT / Codex, or a T3 hybrid version below.

**Status:** v0.5.0. Designed and written, but not yet benchmarked or run end to end, so the savings are a hypothesis until measured.

## Install

No clone needed for any variant. Commands download the published `main` branch; newly added variants become downloadable after they are pushed there. Re-run a command to update that variant. Restart the host or reload its skills after installing.

### Claude Code

**As a plugin** (updates cleanly):

```bash
claude plugin marketplace add Flapjackpants/shippy
claude plugin install shippy@shippy
```

**As plain files** in `~/.claude/` (update by re-running):

```bash
mkdir -p ~/.claude/skills ~/.claude/agents
(set -o pipefail
  curl -fsSL https://github.com/Flapjackpants/shippy/archive/refs/heads/main.tar.gz \
    | tar -xz -C ~/.claude --strip-components=1 shippy-main/skills/shippy shippy-main/agents
)
```

Restart Claude Code afterwards.

### ChatGPT / Codex version (experimental)

The separate [shippy-chatgpt skill](skills/shippy-chatgpt/SKILL.md) uses **GPT-6 Astra as the session orchestrator** and **GPT-6 Sol at medium reasoning** for ordinary implementation stages, and **GPT-6 Luna at medium reasoning** for mechanical stages and command verification. Astra assesses final correctness and test adequacy. The Claude version is unchanged. This port has passed structural validation but has not been run end to end or benchmarked.

| Role | Model |
|---|---|
| Roadmap, stage specs and final assessment | Session, normally GPT-6 Astra |
| Default stages | GPT-6 Sol, medium reasoning |
| Mechanical stages | GPT-6 Luna, medium reasoning |
| Baseline and final test runs | GPT-6 Luna, medium reasoning |

Install without cloning: download the self-contained skill directly into Codex's user skill directory. Re-run this command to update it after changes are published to `main`:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
(set -o pipefail
  curl -fsSL https://github.com/Flapjackpants/shippy/archive/refs/heads/main.tar.gz \
    | tar -xz -C "${CODEX_HOME:-$HOME/.codex}/skills" --strip-components=2 shippy-main/skills/shippy-chatgpt
)
```

Select Astra for the session, then invoke:

```text
$shippy-chatgpt add rate limiting to the public API
```

The host must expose repository tools and subagent model/reasoning controls. The skill checks those capabilities; installing it does not enable them or switch the session model. Its native dispatch example targets the `collaboration.spawn_agent` interface; hosts such as T3 may require their own orchestration service for explicit model settings. In a ChatGPT environment without these tools, the file alone cannot run the pipeline. See the official [subagent documentation](https://developers.openai.com/codex/subagents/) for host availability and configuration.

The port asks clarifying questions with recommendations, gets your approval of the plan, commits each stage by default (no commits only if you or the repository's rules forbid them), and never silently substitutes a different builder model.

### T3 hybrid: free Antigravity and OpenCode workers (experimental)

The self-contained [shippy-t3 skill](skills/shippy-t3/SKILL.md) runs under either a **Claude Opus** or a **GPT-6 Astra** main session in T3. The session plans, writes stage specs and assesses the final result. Free **Antigravity** and **OpenCode** models build stages and run verification commands, best model first for each kind of task. It dispatches them directly and does not check pricing before a run. The order comes from third-party coding benchmarks, not shippy benchmarks; these are task assignments, not claims of equivalence to Sonnet, Sol or Luna. This workflow has not yet been benchmarked or run end to end.

| Role | Free models, best first | Paid fallback |
|---|---|---|
| Roadmap, stage specs and final assessment | Session: Claude Opus or GPT-6 Astra | none |
| High-risk stages (concurrency, auth, crypto, migrations, hard debugging) | DeepSeek V4.1 Flash (OpenCode), Gemini 3.8 Flash (Antigravity), Claude Opus 4.6 (Antigravity) | Sol medium, then Sonnet medium |
| Ordinary stages | Gemini 3.8 Flash (Antigravity), DeepSeek V4.1 Flash (OpenCode), Claude Sonnet 4.6 (Antigravity) | Sol medium, then Sonnet medium |
| Mechanical stages | GLM-5.3-Flash (OpenCode), Claude Sonnet 4.6 (Antigravity), Gemini 3.8 Flash (Antigravity) | Luna medium, then Sonnet medium |
| Baseline and final test runs | GPT-OSS 120B (Antigravity), GLM-5.3-Flash (OpenCode), Gemini 3.8 Flash (Antigravity) | Luna medium, then Haiku medium |

Antigravity models run at medium `thinking_level`. Fallback follows quota pools: Antigravity reports separate Gemini, Claude (shared by Opus 4.6 and Sonnet 4.6) and GPT pools, and each OpenCode model counts as its own pool unless an error names the account. When a pool runs out, the skill skips every model in it and moves to the task's next free model; a model-specific failure skips only that model. Codex and then Claude take over only after all of a task's free models have failed. Say `free-only` to disable paid fallback. Fallback uses each provider's configured subscription/API allowance; the planner still consumes its own allowance.

Provider failures are quota exhaustion, missing or expired models, authentication errors, disabled providers, and rate-limit, overload or network errors that persist after one retry. Failed tests and weak output do not trigger fallback. Because the skill does not check prices, an ended promotion could bill any OpenCode credit before a failure appears. The skill preserves partial work and stops the old worker before replacing it. See [routing and recovery rules](skills/shippy-t3/references/provider-routing.md).

Install it without cloning. For T3's Claude provider:

```bash
mkdir -p ~/.claude/skills
(set -o pipefail
  curl -fsSL https://github.com/Flapjackpants/shippy/archive/refs/heads/main.tar.gz \
    | tar -xz -C ~/.claude/skills --strip-components=2 shippy-main/skills/shippy-t3
)
```

For T3's Codex provider:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
(set -o pipefail
  curl -fsSL https://github.com/Flapjackpants/shippy/archive/refs/heads/main.tar.gz \
    | tar -xz -C "${CODEX_HOME:-$HOME/.codex}/skills" --strip-components=2 shippy-main/skills/shippy-t3
)
```

`shippy-t3` replaces the former `shippy-t3-chatgpt` skill; delete that folder from your Codex skills directory if you installed it.

In T3, select Claude Opus or GPT-6 Astra for the main session and invoke (`$shippy-t3` under Codex):

```text
/shippy-t3 add rate limiting to the public API
```

T3 needs the session's provider, Antigravity and OpenCode enabled, plus Codex and Claude when paid fallback is needed. Install OpenCode using `npm install -g @opencode/cli`, connect Antigravity, enable both in **Settings → Providers**, and refresh provider status. Free models must appear in their catalogs; authenticate fallback providers separately. The skill checks capabilities and uses `delegate_task` for cross-provider execution, passing only supported reasoning options. It does not require other shippy variants or Claude agent files. Installing it in plain Claude Code does not add T3's tools.

As of November 2, 2026, [OpenCode's free-model page](https://opencode.ai/v2/docs/console/models/#free-models) gives no fixed request/token allowance or end date for these DeepSeek/GLM promotions. Free access is not a guaranteed unlimited quota. The published limits for the separate paid [OpenCode Go subscription](https://opencode.ai/v2/docs/console/go/) do not establish the free offers' allowances. On November 10, 2026, T3's Antigravity quota panel showed each pool's remaining quota and reset time (about seven days for Claude and GPT); the skill decides exhaustion from that and from provider errors.

## Usage

The remaining walkthrough describes the original Claude Code variant.

```text
/shippy add rate limiting to the public API
```

A plugin install may list it as `/shippy:shippy`. The target must be a git repository, because shippy commits as it builds.

## How it works

Small changes (about 3 files or fewer, one obvious design, no migration or public-API change) run in **Lean** mode: the session model says why the roadmap is optional, asks any blocking questions, shows a short plan and lets you skip the roadmap or ask for one. If you skip it, the session model writes one stage spec, and a fresh sub-agent builds it test-first and makes one commit.

Everything else runs in **Full** mode:

1. **Roadmap.** The session model investigates read-only, settles every design question with you, and writes a staged roadmap. You approve it and choose to confirm each stage or run automatically.
2. **Stage loop.** Each stage's spec is written just before it is built, with code anchors from the current HEAD, so it can't drift. A fresh sub-agent then writes black-box tests, the implementation and white-box tests, verifies the stage and commits it as one Conventional Commit.
3. **Rundown.** You get a summary and a ready-to-paste PR description. Nothing is pushed.

| Role | Agent | Model |
|---|---|---|
| Roadmap and stage specs | Session | Your session model, normally Opus |
| Default stages | `stage-executor` | Sonnet |
| Purely mechanical stages | `stage-executor` | Haiku |
| Concurrency, auth, crypto, migrations | `stage-executor` | Opus |
| Baseline and final test runs | `plan-verifier` | Haiku |

## How it saves tokens

Every tool call re-reads the agent's whole context, so most of the cost is what agents carry, not what they write. Shippy keeps that small:

- **Fresh builder per stage**, so one stage's test logs and edits aren't re-read through the next.
- **Quiet, failures-only test commands**, because test output is a builder's biggest re-read cost.
- **Short dispatch prompts** that point at line ranges in the plan file instead of retyping the spec.
- **A Haiku verifier** that keeps long test logs out of the session model's context.
- **Cheapest adequate model per stage**, chosen by risk.
