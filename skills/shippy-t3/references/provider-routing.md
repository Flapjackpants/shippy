# Free OpenCode workers and quota-only fallback

## Resolve and record the route

Use T3's capability result to identify the enabled OpenCode instance, its exact model IDs, and option schemas. Require repository/tool access. If the catalog is abbreviated, use the host's read-only model catalog or provider UI; do not guess an ID or repeatedly poll capabilities. If setup or authentication is missing, report it and stop dependent dispatches. Do not enable providers, buy credits or change billing settings as part of this skill.

Before each new run, confirm free pricing from current official OpenCode documentation or the live provider's explicit price metadata. A name containing `free` alone is insufficient. Record the source and date. Paid OpenCode Go models and pay-as-you-go versions of the same model are not free substitutes. Never enable Extra Usage/auto-recharge or point Codex/Claude directly at an OpenCode free endpoint; use T3's OpenCode provider.

Starting preferences (verify availability and pricing; these are not benchmarked equivalences):
- Ordinary implementation, logic, debugging and high-risk stages: DeepSeek V4.1 Flash Free, then GLM-5.3-Flash Free.
- Mechanical stages and command verification: GLM-5.3-Flash Free, then DeepSeek V4.1 Flash Free.

Resolve these names to exact catalog IDs, including any provider prefix. The skill authorizes this two-model free pool; adding other models requires the user's agreement. Keep only currently available, confirmed-free candidates. If none can be verified, report that blocker; absence or promotion expiry is not quota exhaustion. If the same candidate serves both categories, record it without inventing distinct capability tiers.

For supported reasoning controls, prefer medium; otherwise clear inherited options with `target.options: {}` and record the model's default. Do not send Codex's `reasoningEffort` or Claude's `effort` key to an OpenCode model unless capabilities expose it. Announce the selected free pool and fallback family in the visible plan; existing implementation authorization does not require an extra approval gate.

Record in Shared context:
- Free pool: exact provider/model IDs, options, price evidence/date, category preference.
- Fallback family: Codex (default) or Claude (user-selected), exact targets and options.
- Exhaustion ledger: affected account/model/pool, evidence, time and reset time if supplied.
- Stage recovery: files/commits/checks already completed, fix attempts and replacement task IDs.

## Fallback targets

Invocation authorizes the documented fallback after confirmed exhaustion unless the user requests free-only execution. Honor stricter budgets or existing restrictions. Check fallback capabilities before starting; an unavailable fallback remains a blocker if needed, but need not prevent free work.

- Codex default: `gpt-6-sol` with `target.options: {"reasoningEffort":"medium"}` for ordinary/high-risk implementation; `gpt-6-luna` with the same effort for mechanical work and command verification.
- Claude alternative, when selected by the user: `claude-sonnet-5-5` with `target.options: {"effort":"medium"}` for implementation (including mechanical work); `claude-haiku-5-5` with the same effort for command verification.

Resolve provider IDs from capabilities. Preserve these exact generations unless the user chooses another. ChatGPT/Codex or Claude fallback uses that provider's configured subscription/API allowance and may incur cost; do not claim it is free. The Opus orchestrator continues consuming its own allowance throughout.

## When switching is allowed

Only an explicit provider/tool error or authoritative usage status showing an exhausted usage allowance qualifies. Capture a redacted code/message, its scope (model-specific or shared account pool), and reset time when given. A child saying only "out of tokens" is ambiguous: it may mean context length, not account quota. Obtain evidence before switching.

The following do NOT qualify: bare HTTP 429, temporary request/token-per-minute throttling, overload/5xx, network failure, authentication errors, disabled providers, missing models, offer expiry, context-window limits, weak output, failed tests, or a T3 wait timeout. Report the actual condition; do not silently spend on a fallback. For a transient throttle with an explicit short Retry-After, allow at most one retry after the advised delay using the host's permitted mechanism. If no such mechanism is available, or the delay exceeds 60 seconds, hand back the reset/retry time without polling or scheduling work. Persistent/ambiguous errors remain blockers.

For confirmed model-specific exhaustion, try the other eligible model in the recorded free pool once if it has a separate usable allowance. Do not evade shared account limits by rotating models, accounts or keys. When all eligible free routes are confirmed exhausted, or a shared quota covers the whole pool, announce the evidence and use the recorded Codex/Claude fallback without asking again. Free-only mode stops instead.

## Bounded recovery

Before any replacement, ensure the old task is terminal or cancel it with `task_cancel`; no overlapping writers. Inspect git status, diff stat and recent commits to recover actual progress, including work done after the last report. Preserve user edits and completed commits. If the stage already completed, verify its evidence rather than rebuilding it.

Dispatch a fresh child with the stage ranges, partial-work ownership, last completed checks, remaining work, failure evidence and existing fix-attempt count. Carry this context across providers; do not restart the entire plan or repeat checks already completed with reliable evidence. An interrupted check without an exit code is incomplete. Use at most one attempt per eligible free route and one paid fallback for a quota recovery; do not chain paid providers if fallback also exhausts or fails.

Persist exhaustion evidence across later stages. Do not repeatedly probe an exhausted route. Return to the preferred free route only at a stage boundary after its documented reset time or an authoritative status shows renewed allowance; never switch an active builder. If the reset time is unknown, keep the exhausted status for the run and disclose it. Re-evaluate pricing if a promotion changes during the run.

## Published limits

Checked November 2, 2026: OpenCode's [free-model documentation](https://opencode.ai/v2/docs/console/models/#free-models) labels the DeepSeek and GLM offers "limited time" but gives neither a fixed token/request allocation nor an end date there. Do not invent a quota, promise unlimited availability, or infer a promotion deadline from another model's discount or data-retention agreement.

[OpenCode Go](https://opencode.ai/v2/docs/console/go/) is a separate paid subscription with published usage limits. Its quotas and estimated request counts are not the allowance for these free-model offers. Use actual provider evidence to decide exhaustion, not an estimated number of completed coding tasks.
