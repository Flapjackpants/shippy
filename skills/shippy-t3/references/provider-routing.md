# Free worker routes and fallback chain

## Resolve and record the route

Use T3's capability result to identify enabled providers, their exact model IDs and option schemas. Require repository/tool access. If the capability list is abbreviated, dispatch a route anyway: when its provider is enabled and can run child tasks, use the routes file's exact model ID and options even if the model is unlisted, with no catalog search, provider UI or second capabilities call to confirm it, and never an ID the routes file does not give. A model-not-found error is a model-specific provider failure ([provider-recovery.md](provider-recovery.md)); re-call capabilities only if the call itself failed or the user names a provider change, never to diagnose a dispatch error. Missing provider setup or authentication is a provider failure; see [provider-recovery.md](provider-recovery.md). Do not enable providers, buy credits or change billing settings as part of this skill.

Do not check pricing before a run; dispatch the free routes directly. If a provider response or status shows a charge on a free model, treat it as a provider failure and report it. Paid OpenCode Go models and pay-as-you-go versions of the same model are not free substitutes. Never enable Extra Usage/auto-recharge or point Codex/Claude directly at a free endpoint; use T3's own providers.

Routes come from `~/.config/shippy/t3-routes.md` if it exists, otherwise [default-routes.md](default-routes.md); the user edits them with `scripts/configure.py`. Each line gives one category's free routes, best first, then its fallbacks. Categories: high-risk (concurrency, auth, crypto, migrations, hard debugging), ordinary (implementation and logic), mechanical, and verification (command runs). The ranking comes from third-party benchmarks, not shippy benchmarks. Use each entry's provider, model and options exactly; skip entries whose provider capabilities show as disabled, unauthenticated or unable to run child tasks. The routes file authorizes its models; others need the user's agreement.

`[pool X]` entries share quota pool X; an untagged model is its own pool unless an error names the account. `[limited]` marks a small or unclear free allowance: expect early exhaustion and report any charge.

Send each entry's options as `target.options`; `{}` clears inherited settings. Do not add reasoning keys that capabilities do not expose. For an unlisted model, send the routes file's options unchanged. Include the routes in the plan shown for approval.

Record in Shared context:
- Free routes: exact provider/model IDs, options and order per category.
- Fallback chain: exact targets and options for each step, and any step found unavailable.
- Failure ledger: affected provider/model/quota pool, evidence, time and reset time if supplied.
- Stage recovery: files/commits/checks already completed, fix attempts and replacement task IDs.

## Fallback chain

Invocation authorizes the routes file's fallbacks, in order, once a category's free routes have failed, unless the user requests free-only execution. Honor stricter budgets or existing restrictions. Check a fallback's capabilities when it is first needed; skip an unavailable one. An unavailable fallback need not prevent free work.

Paid fallbacks such as Codex or Claude use that provider's subscription/API allowance and may incur cost; do not claim they are free. Preserve the listed model generations unless the user chooses another. The orchestrator consumes its own allowance throughout; a Gemini orchestrator draws on the Antigravity Gemini pool that Gemini workers also use.

On any provider error, read [provider-recovery.md](provider-recovery.md) before retrying, switching or replacing a task.
