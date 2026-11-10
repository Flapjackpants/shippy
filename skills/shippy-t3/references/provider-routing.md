# Free worker routes and fallback chain

## Resolve and record the route

Use T3's capability result to identify enabled providers, their exact model IDs and option schemas. Require repository/tool access. If the catalog is abbreviated, use the host's read-only model catalog or provider UI; do not guess an ID or repeatedly poll capabilities. Missing provider setup or authentication is a provider failure; see When switching is allowed. Do not enable providers, buy credits or change billing settings as part of this skill.

Do not check pricing before a run; dispatch the free routes directly. If a provider response or status shows a charge on a free model, treat it as a provider failure and report it. Paid OpenCode Go models and pay-as-you-go versions of the same model are not free substitutes. Never enable Extra Usage/auto-recharge or point Codex/Claude directly at a free endpoint; use T3's own providers.

Routes come from `~/.config/shippy/t3-routes.md` if it exists, otherwise [default-routes.md](default-routes.md); the user edits them with `scripts/configure.py`. Each line gives one category's free routes, best first, then its fallbacks. Categories: high-risk (concurrency, auth, crypto, migrations, hard debugging), ordinary (implementation and logic), mechanical, and verification (command runs). The ranking comes from third-party benchmarks, not shippy benchmarks. Use each entry's provider, model and options exactly; skip entries that capabilities do not list. The routes file authorizes its models; others need the user's agreement.

`[pool X]` entries share quota pool X; an untagged model is its own pool unless an error names the account. `[limited]` marks a small or unclear free allowance: expect early exhaustion and report any charge.

Send each entry's options as `target.options`; `{}` clears inherited settings. Do not add reasoning keys that capabilities do not expose. Include the routes in the plan shown for approval.

Record in Shared context:
- Free routes: exact provider/model IDs, options and order per category.
- Fallback chain: exact targets and options for each step, and any step found unavailable.
- Failure ledger: affected provider/model/quota pool, evidence, time and reset time if supplied.
- Stage recovery: files/commits/checks already completed, fix attempts and replacement task IDs.

## Fallback chain

Invocation authorizes the routes file's fallbacks, in order, once a category's free routes have failed, unless the user requests free-only execution. Honor stricter budgets or existing restrictions. Check a fallback's capabilities when it is first needed; skip an unavailable one. An unavailable fallback need not prevent free work.

Paid fallbacks such as Codex or Claude use that provider's subscription/API allowance and may incur cost; do not claim they are free. Preserve the listed model generations unless the user chooses another. The orchestrator consumes its own allowance throughout; a Gemini orchestrator draws on the Antigravity Gemini pool that Gemini workers also use.

## When switching is allowed

Only a provider failure qualifies, shown by an explicit provider/tool error or authoritative status: exhausted usage allowance; a missing or expired model; an authentication error or disabled provider; or a 429, overload, 5xx or network failure that persists after one retry. Capture a redacted code/message, its scope (model-specific or shared account pool), and reset time when given. A child saying only "out of tokens" is ambiguous: it may mean context length, not account quota. Obtain evidence before switching.

The following do NOT qualify: context-window limits, weak output, failed tests, coding failures, or a T3 wait timeout. Report the actual condition; do not silently spend on a fallback. Allow one retry for a transient error, after any advised delay of up to 60 seconds using the host's permitted mechanism. If no such mechanism is available, or the delay is longer, count the failure as persistent without polling or scheduling work.

On a failure, skip what it covers: exhausted usage removes its whole quota pool, and a model-specific failure removes only that model. Then try the category's next free route. Do not evade shared limits by rotating models within an exhausted pool, or by switching accounts or keys. When no free route remains, announce the evidence and use the first fallback without asking again; on its provider failure, use the next. If none remains, hand back the blocker. Free-only mode stops after the last free route.

## Bounded recovery

Before any replacement, ensure the old task is terminal or cancel it with `task_cancel`; no overlapping writers. Inspect git status, diff stat and recent commits to recover actual progress, including work done after the last report. Preserve user edits and completed commits. If the stage already completed, verify its evidence rather than rebuilding it.

Dispatch a fresh child with the stage ranges, partial-work ownership, last completed checks, remaining work, failure evidence and existing fix-attempt count. Carry this context across providers; do not restart the entire plan or repeat checks already completed with reliable evidence. An interrupted check without an exit code is incomplete. Use at most one attempt per chain step for a recovery.

Persist failure evidence across later stages. Do not repeatedly probe a failed route. Return to the preferred free route only at a stage boundary after its documented reset time (T3's quota panel may show one) or an authoritative status shows renewed allowance; never switch an active builder. A non-quota failure may be retried once at the next stage boundary. If an exhausted route's reset time is unknown, keep that status for the run and disclose it.
