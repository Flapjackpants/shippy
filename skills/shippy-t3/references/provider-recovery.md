# Provider failure and recovery

## When switching is allowed

Only a provider failure qualifies, shown by an explicit provider/tool error or authoritative status: exhausted usage allowance; a missing or expired model; an authentication error or disabled provider; or a 429, overload, 5xx or network failure that persists after one retry. Capture a redacted code/message, its scope (model, pool or provider) and reset time when given. A child saying only "out of tokens" is ambiguous: it may mean context length, not account quota.

Classify only from the task's terminal error: the failure notification, or one `task_status` if it carries none. Never read the child's thread to diagnose, no `t3_thread_read`. With no error at all, treat the task as transient once, then as a failure.

The following do NOT qualify: context-window limits, weak output, failed tests, coding failures, or a T3 wait timeout. Report the actual condition; do not silently spend on a fallback. Allow one retry for a transient error, after any advised delay of up to 60 seconds using the host's permitted mechanism. Otherwise count the failure as persistent, without polling or scheduling work.

Scope a failure by what it removes:
- exhausted usage: its whole quota pool, no retry, until the reset time (else the rest of the run);
- missing, expired or not-found model: that model only;
- auth error, disabled provider, or network/5xx persisting after one retry: every entry of that provider;
- 429 or overload persisting after one retry, or Retry-After over 60 seconds: its quota pool (an untagged model is its own).

Next is a lookup: the category's first free route, then fallbacks, whose provider, pool and model are absent from the ledger. One removal applies to every category; do not re-call capabilities or re-rank. Do not evade shared limits by rotating models in an exhausted pool or switching accounts or keys. When no free route remains, announce the evidence and use the first fallback unasked; on its provider failure, use the next. If none remains, hand back the blocker. Free-only mode stops after the last free route. Provider- and model-scope removals may be retried once at the next stage boundary; quota removals wait for reset.

## Bounded recovery

Before any replacement, ensure the old task is terminal or cancel it with `task_cancel`; no overlapping writers. Run only `git status --porcelain`; if anything outside the stage's files changed, stop and report. Do not read the diff to recover progress. If the stage already committed, verify its evidence rather than rebuilding it.

Send a fresh child the stage's original task text unchanged plus a resume block: failure code, stage start HEAD, fix-attempt count, checks passed with exit codes, and "partial edits may exist in owned files: inspect `git status`/`git diff` for them, keep valid work, finish the stage". A paid fallback gets the same delta, not a richer brief. Use at most one attempt per chain step for a recovery.

Persist the ledger across stages. Do not repeatedly probe a failed route. Return to the preferred free route only at a stage boundary, after its reset time or renewed authoritative status; never switch an active builder. If an exhausted route's reset time is unknown, keep that status for the run and disclose it.
