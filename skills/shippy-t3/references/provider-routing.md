# Free Antigravity and OpenCode workers and fallback chain

## Resolve and record the route

Use T3's capability result to identify the enabled Antigravity and OpenCode instances, their exact model IDs, and option schemas. Require repository/tool access. If the catalog is abbreviated, use the host's read-only model catalog or provider UI; do not guess an ID or repeatedly poll capabilities. Missing provider setup or authentication is a provider failure; see When switching is allowed. Do not enable providers, buy credits or change billing settings as part of this skill.

Do not check pricing before a run; dispatch the free routes directly. If a provider response or status shows a charge on a free model, treat it as a provider failure and report it. Paid OpenCode Go models and pay-as-you-go versions of the same model are not free substitutes. Never enable Extra Usage/auto-recharge or point Codex/Claude directly at a free endpoint; use T3's Antigravity and OpenCode providers.

Free routes per task category, best first. These are starting preferences ranked from third-party coding benchmarks, not shippy benchmarks; each category starts on a different quota pool to spread load.

| Category | Free routes, in order | Paid chain |
|---|---|---|
| High-risk (concurrency, auth, crypto, migrations, hard debugging) | DeepSeek V4.1 Flash (OC), Gemini 3.8 Flash (AG), Opus 4.6 (AG) | Sol, then Sonnet |
| Ordinary implementation and logic | Gemini 3.8 Flash (AG), DeepSeek V4.1 Flash (OC), Sonnet 4.6 (AG) | Sol, then Sonnet |
| Mechanical stages | GLM-5.3-Flash (OC), Sonnet 4.6 (AG), Gemini 3.8 Flash (AG) | Luna, then Sonnet |
| Command verification | GPT-OSS 120B (AG), GLM-5.3-Flash (OC), Gemini 3.8 Flash (AG) | Luna, then Haiku |

AG is Antigravity, OC is OpenCode. Resolve each name to its exact catalog ID, such as `gemini-3.8-flash`, `claude-opus-4-6-thinking`, `claude-sonnet-4-6`, `gpt-oss-120b-medium`, `opencode/deepseek-v4.1-flash-free` and `opencode/glm-5.3-flash-free`. The skill authorizes these six free models; adding others requires the user's agreement. Skip a route the catalog does not list.

Quota pools: Antigravity reports separate Gemini, Claude (shared by Opus 4.6 and Sonnet 4.6) and GPT pools. Treat each OpenCode model as its own pool unless an error names the account.

For supported reasoning controls, prefer medium (Antigravity's `thinking_level`); otherwise clear inherited options with `target.options: {}` and record the model's default. Do not send Codex's `reasoningEffort` or Claude's `effort` key to an Antigravity or OpenCode model unless capabilities expose it. Include the free routes and fallback chain in the plan shown for approval.

Record in Shared context:
- Free routes: exact provider/model IDs, options and order per category.
- Fallback chain: exact targets and options for each step, and any step found unavailable.
- Failure ledger: affected provider/model/quota pool, evidence, time and reset time if supplied.
- Stage recovery: files/commits/checks already completed, fix attempts and replacement task IDs.

## Fallback chain

Invocation authorizes the paid chain once a category's free routes have failed, unless the user requests free-only execution. Honor stricter budgets or existing restrictions. Check a step's capabilities when it is first needed; skip an unavailable step. An unavailable step need not prevent free work.

- First, Codex: `gpt-6-sol` with `target.options: {"reasoningEffort":"medium"}` for ordinary/high-risk implementation; `gpt-6-luna` with the same effort for mechanical work and command verification.
- Last, Claude: `claude-sonnet-5-5` with `target.options: {"effort":"medium"}` for implementation (including mechanical work); `claude-haiku-5-5` with the same effort for command verification.

Resolve provider IDs from capabilities. Preserve these exact generations unless the user chooses another. ChatGPT/Codex or Claude fallback uses that provider's configured subscription/API allowance and may incur cost; do not claim it is free. The orchestrator continues consuming its own allowance throughout.

## When switching is allowed

Only a provider failure qualifies, shown by an explicit provider/tool error or authoritative status: exhausted usage allowance; a missing or expired model; an authentication error or disabled provider; or a 429, overload, 5xx or network failure that persists after one retry. Capture a redacted code/message, its scope (model-specific or shared account pool), and reset time when given. A child saying only "out of tokens" is ambiguous: it may mean context length, not account quota. Obtain evidence before switching.

The following do NOT qualify: context-window limits, weak output, failed tests, coding failures, or a T3 wait timeout. Report the actual condition; do not silently spend on a fallback. Allow one retry for a transient error, after any advised delay of up to 60 seconds using the host's permitted mechanism. If no such mechanism is available, or the delay is longer, count the failure as persistent without polling or scheduling work.

On a failure, skip what it covers: exhausted usage removes its whole quota pool, and a model-specific failure removes only that model. Then try the category's next free route. Do not evade shared limits by rotating models within an exhausted pool, or by switching accounts or keys. When no free route remains, announce the evidence and use the Codex step without asking again. If Codex also has a provider failure, use the Claude step. If no step remains, hand back the blocker. Free-only mode stops after the last free route.

## Bounded recovery

Before any replacement, ensure the old task is terminal or cancel it with `task_cancel`; no overlapping writers. Inspect git status, diff stat and recent commits to recover actual progress, including work done after the last report. Preserve user edits and completed commits. If the stage already completed, verify its evidence rather than rebuilding it.

Dispatch a fresh child with the stage ranges, partial-work ownership, last completed checks, remaining work, failure evidence and existing fix-attempt count. Carry this context across providers; do not restart the entire plan or repeat checks already completed with reliable evidence. An interrupted check without an exit code is incomplete. Use at most one attempt per chain step for a recovery.

Persist failure evidence across later stages. Do not repeatedly probe a failed route. Return to the preferred free route only at a stage boundary after its documented reset time (Antigravity's quota panel shows one per pool) or an authoritative status shows renewed allowance; never switch an active builder. A non-quota failure may be retried once at the next stage boundary. If an exhausted route's reset time is unknown, keep that status for the run and disclose it.

## Published limits

Checked November 2, 2026: OpenCode's [free-model documentation](https://opencode.ai/v2/docs/console/models/#free-models) labels the DeepSeek and GLM offers "limited time" but gives neither a fixed token/request allocation nor an end date there. Do not invent a quota, promise unlimited availability, or infer a promotion deadline from another model's discount or data-retention agreement.

[OpenCode Go](https://opencode.ai/v2/docs/console/go/) is a separate paid subscription with published usage limits. Its quotas and estimated request counts are not the allowance for these free-model offers. Use actual provider evidence to decide exhaustion, not an estimated number of completed coding tasks.

Observed November 10, 2026: T3's Antigravity quota panel reports Gemini, Claude and GPT pools separately, each with a reset time (Claude and GPT showed about seven days). Use reported quota and provider errors to decide exhaustion; do not invent an allowance.
