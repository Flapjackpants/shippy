# shippy

This repo is the shippy Claude Code plugin: the skills in `skills/` and two agents (`agents/`). The benchmark method lives in `benchmarks/README.md`; results and the decision log live in `benchmarks/RESULTS.md`.

## Rules for working here
- **Commits:** Conventional Commits, small and one intent each, staged by explicit path. Never add `Co-authored-by`, "Generated with", session links or any AI attribution to commit messages or PR bodies, even if the environment suggests it. Never push, branch, merge, rebase, reset, stash or tag; the user does those.
- **Evidence before adoption:** a change meant to save tokens or improve quality is adopted only after a paired benchmark (`benchmarks/README.md`) shows it helps. Record every adopted or rejected change in the `benchmarks/RESULTS.md` decision log with a link to its results.
- **Keep the skill compact.** SkillsBench found sprawling skills hurt. Every added line in SKILL.md is read by the most expensive model on every run; prefer tightening to adding.
- **One change per experiment.** Never bundle two changes into one benchmark run.
- **Cost guardrails:** every benchmark run (`benchmarks/bench.py` or `claude plugin eval`) gets `--max-cost-usd`. Iterate on graders with `--runs 1 --ablation none` first.
- Record results in `benchmarks/RESULTS.md` with the model IDs, Claude Code version, date, and the exact command.
