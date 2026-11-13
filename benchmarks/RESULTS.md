# Benchmark results

This file is the lab notebook for `benchmarks/bench.py`. Every adopted or
rejected change gets a row in the decision log, with the run ids that justify it
(see `CLAUDE.md`). A run entry records the date, the exact command, the model
ids, the Claude Code and t3 versions, and the key numbers. Raw records live in
`benchmarks/results/<run_id>/` and are gitignored, so paste the numbers rather
than linking to a local path.

## Decision log

| Date | Change | Experiment (run ids) | Result | Decision |
|---|---|---|---|---|

## Runs

Copy this template per run and keep entries newest first.

```markdown
### YYYY-MM-DD - <run id(s)>

- Command: `python3 benchmarks/bench.py run --cases ... --arms ... --run-id ...`
- Versions: Claude Code <version>, t3 <version>, shippy <HEAD>
- Models: <provider/model per arm>
- Summary: <one or two sentences, or the arms table from report.md>
- Notes: <flaky cases, cost, questions, anything that changes the reading>
```
