# shippy

A family of skills for a plan-then-build pipeline: the orchestrator plans, focused agents build, and every agent carries only what it needs. Choose the Claude, ChatGPT / Codex, or T3 hybrid version below.

**Status:** v0.5.0. Designed and written, but not yet benchmarked or run end to end, so the savings are a hypothesis until measured. The benchmark plan is in [HANDOFF.md](HANDOFF.md).

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

The port honors existing implementation authorization and requested approval gates, supports per-stage local commits or no commits, and never silently substitutes a different builder model.

### T3 hybrid: Claude + Sol / Luna (experimental)

The self-contained [shippy-t3 skill](skills/shippy-t3/SKILL.md) uses **Claude Opus as the main orchestrator**, **GPT-6 Sol at medium reasoning** for ordinary implementation stages, and **GPT-6 Luna at medium reasoning** for mechanical stages and baseline/final command verification. Claude assesses the final result against the requirements. This workflow has not yet been benchmarked or run end to end.

Install it for T3's Claude provider, without cloning:

```bash
mkdir -p ~/.claude/skills
(set -o pipefail
  curl -fsSL https://github.com/Flapjackpants/shippy/archive/refs/heads/main.tar.gz \
    | tar -xz -C ~/.claude/skills --strip-components=2 shippy-main/skills/shippy-t3
)
```

In T3, select Claude Opus for the main session and invoke:

```text
/shippy-t3 add rate limiting to the public API
```

T3 must have both Claude and Codex providers enabled and authenticated. The skill checks T3's model capabilities, then uses `delegate_task` for cross-provider execution with explicit reasoning settings. It does not require the other shippy variants or the Claude agent files. It supports per-stage commits or no commits, preserves requested approval gates, and asks before substituting an unavailable model. Installing it in plain Claude Code does not add T3's tools.

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

The reasoning, the research behind it and the rejected alternatives are in [HANDOFF.md](HANDOFF.md).
