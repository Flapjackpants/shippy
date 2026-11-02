# shippy

A Claude Code skill that replaces plan mode with a plan-then-build pipeline. Its goal is to use as few tokens as possible for the best code: the expensive model plans, cheaper models build, and every agent carries only what it needs.

**Status:** v0.5.0. Designed and written, but not yet benchmarked or run end to end, so the savings are a hypothesis until measured. The benchmark plan is in [HANDOFF.md](HANDOFF.md).

## Install

No clone needed. Pick one.

**As a plugin** (updates cleanly):

```bash
claude plugin marketplace add Flapjackpants/shippy
claude plugin install shippy@shippy
```

**As plain files** in `~/.claude/` (update by re-running):

```bash
mkdir -p ~/.claude/skills ~/.claude/agents
curl -fsSL https://github.com/Flapjackpants/shippy/archive/refs/heads/main.tar.gz \
  | tar -xz -C ~/.claude --strip-components=1 shippy-main/skills/shippy shippy-main/agents
```

Restart Claude Code afterwards.

## Usage

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
