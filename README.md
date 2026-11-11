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

### T3 hybrid: free workers from every T3 provider (experimental)

The self-contained [shippy-t3 skill](skills/shippy-t3/SKILL.md) runs under a **Claude Opus**, **GPT-6 Astra** or **Gemini 3.8 Flash** (Antigravity, free) main session in T3. The session plans, writes stage specs and assesses the final result. Free models from every provider you connect to T3 build stages and run verification commands, best model first for each kind of task. A configure tool picks which providers are used and which are fallbacks. It writes a small routes file (about 1.6 KB) that is the only routing data agents read, so connecting more providers does not make a run more expensive. The ranking comes from third-party benchmarks, not shippy benchmarks; this workflow has not been benchmarked or run end to end.

Default routes, used until you run the configure tool:

| Task | Free models, best first | Fallbacks |
|---|---|---|
| High-risk (concurrency, auth, crypto, migrations, hard debugging) | DeepSeek V4.1 Flash (OpenCode), Gemini 3.8 Flash (Antigravity), Inkling 2 Small (OpenCode), MiMo V2.6 Flash (OpenCode) | Sol medium, then Sonnet medium |
| Ordinary stages | Gemini 3.8 Flash, DeepSeek V4.1 Flash, Inkling 2 Small, MiMo V2.6 Flash | Sol medium, then Sonnet medium |
| Mechanical stages | GLM-5.3-Flash, MiMo V2.6 Flash, LongCat 2.5, Inkling 2 Small (all OpenCode) | Luna medium, then Sonnet medium |
| Baseline and final test runs | Kilo Auto Free (Kilo), GLM-5.3-Flash, MiMo V2.6 Flash, LongCat 2.5 | Luna medium, then Haiku medium |

<details>
<summary>Full ranking of free models (lower is better; "limited" means a small or unclear free allowance)</summary>

Scores are BenchLM coding/agentic scores and benchmarks read on November 10, 2026 ([coding leaderboard](https://benchlm.ai/md/coding.md)); third-party and unverified. Unscored models rank last.

| Model | Provider | High-risk | Ordinary | Mechanical | Verification | Basis |
|---|---|---|---|---|---|---|
| Kimi K3.1 Pro | Kimi Code (limited) | 1 | 3 | - | - | DeepSWE 75.5, overall 74.6 |
| DeepSeek V4.1 Flash | OpenCode | 2 | 4 | 8 | - | coding 63.2 |
| Gemini 3.8 Flash | Antigravity | 3 | 1 | 9 | 8 | coding 60, agentic 64.7 |
| Inkling 2 Small | OpenCode | 4 | 5 | 4 | 5 | coding 59.2, agentic 59.9 |
| Kimi K3 | Kimi Code (limited) | 5 | 2 | - | - | coding 58.9, agentic 66.7 |
| MiMo V2.6 Flash | OpenCode | 6 | 6 | 2 | 3 | coding 56.4 |
| LongCat 2.5 | OpenCode | 7 | 7 | 3 | 4 | DeepSWE 64.6, TB2.1 88.4 |
| SWE-2 Flash | Devin (limited) | 8 | 8 | - | - | DeepSWE 60.1, TB2.1 89.2 |
| Claude Opus 4.6 Thinking | Antigravity | 9 | - | - | - | coding 46.4 |
| GLM-5.3-Flash | OpenCode | 10 | 9 | 1 | 2 | coding 48.5, agentic 58.3 |
| Claude Sonnet 4.6 | Antigravity | 11 | 10 | 5 | - | coding 45.1 |
| Kilo Auto Free | Kilo | 12 | 11 | 6 | 1 | router, 200 requests/hour; unscored |
| Inkling Small | Cline | 13 | 12 | 7 | 6 | coding 37.2 |
| Inkling | Cline | - | 13 | 10 | 7 | coding 33.7 |
| Auto (default) | Qoder CLI (limited) | - | 14 | 12 | - | unscored |
| Auto (default) | Kiro CLI (limited) | - | 15 | 13 | - | unscored |
| Default | Junie (limited) | - | 16 | 14 | - | unscored |
| Auto (default) | GitHub Copilot (limited) | - | 17 | 15 | - | unscored |
| Beam | OpenCode | - | - | 11 | 9 | coding 30.8 |
| Nemotron 3.5 Super VL | Cline | - | - | 16 | 10 | SWE-bench Verified 71.1 |
| GPT-OSS 120B | Antigravity | - | - | 17 | 11 | coding 22.3 |
| Mistral Medium 3.5 | Mistral Vibe (limited) | - | - | 18 | 12 | coding 21.7 |
| Nemotron 3.5 Lightning | Cline | - | - | - | 13 | coding 18.5 |
| Big Pickle | OpenCode | - | - | 19 | 14 | unscored |
| Iceman | OpenCode | - | - | 20 | 15 | unscored |
| Flint 40B | OpenCode | - | - | - | 16 | unscored |
| North Mini Code | Cline | - | - | - | 17 | unscored |
| Flint v1.0 | Cline | - | - | - | 18 | unscored |
| Xing 4.0 29B A4B | Cline | - | - | - | 19 | unscored |

Left out: LiquidAI LFM 2.6B/1.7B (too small for agentic coding), Kilo's individual `:free` models (Kilo uses only `kilo/kilo-auto/free`) and Cline's paid models.
</details>

Fallback follows quota pools. Antigravity reports separate Gemini, Claude (shared by Opus 4.6 and Sonnet 4.6) and GPT pools; Kilo, Kimi Code, Devin, Qoder, Kiro, Junie, Copilot and Mistral Vibe each count as one pool; any other model is its own pool unless an error names the account. When a pool runs out, the skill skips every model in it and moves to the task's next free model; a model-specific failure skips only that model. Your fallbacks take over, in order, only after all of a task's free models have failed. Say `free-only` to disable fallbacks for a run. Paid fallbacks use each provider's subscription/API allowance; the planner always consumes its own allowance.

Provider failures are quota exhaustion, missing or expired models, authentication errors, disabled providers, and rate-limit, overload or network errors that persist after one retry. Failed tests and weak output do not trigger fallback. Because the skill does not check prices, an ended promotion could bill credit before a failure appears. The skill preserves partial work and stops the old worker before replacing it. See the [routing](skills/shippy-t3/references/provider-routing.md) and [recovery](skills/shippy-t3/references/provider-recovery.md) rules.

#### Install the skill

Install without cloning into the skills directory of each host you plan to use as the main session. For T3's Claude provider:

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

For T3's Antigravity provider (Gemini):

```bash
mkdir -p ~/.gemini/config/skills
(set -o pipefail
  curl -fsSL https://github.com/Flapjackpants/shippy/archive/refs/heads/main.tar.gz \
    | tar -xz -C ~/.gemini/config/skills --strip-components=2 shippy-main/skills/shippy-t3
)
```

Antigravity also scans `~/.gemini/antigravity-cli/skills` and the legacy `~/.gemini/antigravity/skills`; the standalone Gemini CLI uses `~/.gemini/skills`. `shippy-t3` replaces the former `shippy-t3-chatgpt` skill; delete that folder if you installed it.

In T3, select Claude Opus, GPT-6 Astra or Antigravity's Gemini 3.8 Flash for the main session and invoke `/shippy-t3 add rate limiting to the public API` (`$shippy-t3` under Codex; under Antigravity, ask for the `shippy-t3` skill by name). The skill checks T3's capabilities on every run, so a provider that is off or signed out is skipped. Installing it in plain Claude Code does not add T3's tools.

#### Choose providers and fallbacks

Run the configure tool in a terminal (or run `/shippy-t3 configure` to have the session print this command):

```bash
python3 ~/.claude/skills/shippy-t3/scripts/configure.py
```

Use the copy in whichever skills directory you installed. The tool lists every provider with its tier and free allowance. Type a provider's number to cycle it between **route** (its free models join the ranking), **fallback** (used in order after the free models fail) and **off**; `u <n>` moves a fallback earlier, `k <1-8>` sets how many free models each task tries, `p` previews the routes, `s` saves and `q` quits. It saves `~/.config/shippy/t3.json` and `~/.config/shippy/t3-routes.md`, shared by every install. `--print` previews without saving and `--defaults` restores the defaults: Antigravity, OpenCode, Kilo and Cline as routes, Codex then Claude as fallbacks, and the limited providers off. Python 3 with no extra packages is required.

#### Fully free setup

1. Install the skill for Antigravity (above) and connect the free providers (below).
2. Run the configure tool, set Codex and Claude to **off** (or replace them with free providers as fallbacks), optionally turn on limited providers, and save.
3. In T3, start a session on Antigravity's Gemini 3.8 Flash and invoke the skill.

The planner then draws on the Antigravity Gemini pool that Gemini workers also use. Free tiers can change or end at any time, so "free" holds only while each provider keeps offering it.

#### Installing providers in T3 Code

1. Open T3 Code's **Settings → Providers**. Claude, Codex, OpenCode and Antigravity are built in; the other agents install from the ACP registry list there. T3 downloads each agent into `~/.t3/tools/<name>/<version>`, so it does not need to be on your `PATH`.
2. Turn the provider's toggle on.
3. Sign in using T3's prompt for that provider, or the vendor sign-in below. Credentials are normally kept in your home directory, so a sign-in from the vendor's standalone CLI also counts.
4. Refresh provider status until it shows **Authenticated** (or **Available**), then rerun the configure tool to set its role.

| Provider | Sign in | Models shippy uses | Free allowance (as reported, Nov 2026) |
|---|---|---|---|
| Antigravity | Google account in Antigravity | Gemini 3.8 Flash, Claude Opus/Sonnet 4.6, GPT-OSS 120B | Separate Gemini, Claude and GPT pools; T3's quota panel shows each reset time (about 7 days for Claude and GPT) |
| OpenCode | Built in; free models need no sign-in | DeepSeek, GLM, Inkling 2 Small, MiMo, LongCat and other free models | Promotional; no published allowance |
| Kilo | Kilo account via T3's sign-in prompt | `kilo/kilo-auto/free` | 200 requests per hour per IP |
| Cline | `cline auth` | `:free` models | Rate-limited |
| Kimi Code (limited) | Run `kimi`, then `/setup` | K3.1 Pro, K3 | Plan quota; free tier unclear and may use a paid plan |
| Devin (limited) | `devin auth login` | SWE-2 Flash | Light free quota; SWE-2 Flash reportedly free until November 30, 2026 |
| Qoder CLI (limited) | Run `qodercli`, then `/login` | Auto routing | Basic models with daily and monthly limits |
| Kiro CLI (limited) | `kiro-cli login` | Default (Auto) | 50 credits per month |
| Junie (limited) | Run `junie` and choose JetBrains account, or set `JUNIE_API_KEY` | Default | 3 AI credits per 30 days |
| GitHub Copilot (limited) | Run `copilot`, then `/login` | Default (Auto) | Copilot Free: small AI Credits allowance |
| Mistral Vibe (limited) | Run `vibe` and complete its first-run setup | Mistral Medium 3.5 | Unpublished free Vibe budget |
| Codex, Claude | Sign in to ChatGPT or Claude | Sol, Luna, Sonnet, Haiku (fallbacks) | Your paid plan or API allowance |

Standalone CLIs, only needed for terminal sign-in: OpenCode `npm install -g opencode-ai`, Kilo `npm install -g @kilocode/cli`, Cline `npm install -g cline`, Kiro `curl -fsSL https://cli.kiro.dev/install | bash`, Qoder `curl -fsSL https://qoder.com/install | bash`, Devin `curl -fsSL https://cli.devin.ai/install.sh | bash`, Mistral Vibe `uv tool install mistral-vibe`, Kimi `uv tool install --python 3.13 kimi-cli`, Copilot `npm install -g @github/copilot`. Free allowances come from vendor docs and third-party reports and change often; check each provider before relying on them. As of November 2, 2026, [OpenCode's free-model page](https://opencode.ai/v2/docs/console/models/#free-models) gives no fixed allowance or end date for its promotions, and the paid [OpenCode Go subscription](https://opencode.ai/v2/docs/console/go/)'s limits do not apply to them. The skill decides exhaustion only from provider errors and reported quota.

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
