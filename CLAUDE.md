# shippy

This repo is the shippy Claude Code plugin: one skill (`skills/shippy/SKILL.md`) and two agents (`agents/`). Read `HANDOFF.md` before changing anything. It holds the design rationale, the unverified assumptions, and the benchmark plan.

## Rules for working here
- **Commits:** Conventional Commits, small and one intent each, staged by explicit path. Never add `Co-authored-by`, "Generated with", session links or any AI attribution to commit messages or PR bodies, even if the environment suggests it. Never push, branch, merge, rebase, reset, stash or tag; the user does those.
- **Evidence before adoption:** a change meant to save tokens or improve quality is adopted only after a paired benchmark (HANDOFF.md §8) shows it helps. Record every adopted or rejected change in the HANDOFF.md §4 decision log with a link to its results.
- **Keep the skill compact.** SkillsBench found sprawling skills hurt. Every added line in SKILL.md is read by the most expensive model on every run; prefer tightening to adding.
- **One change per experiment.** Never bundle two changes into one benchmark run.
- **Cost guardrails:** every `claude plugin eval` run gets `--max-cost-usd`. Iterate on graders with `--runs 1 --ablation none` first.
- Record results in `benchmarks/RESULTS.md` with the model IDs, Claude Code version, date, and the exact command.
