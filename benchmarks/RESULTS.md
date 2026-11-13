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

### 2026-11-12 - smoke-controls, smoke-claude

Smoke test of the harness only. One run per arm proves nothing about the workflows.

- Commands:
  - `python3 benchmarks/bench.py run --cases all --arms oracle,null --run-id smoke-controls --no-judge`
  - `python3 benchmarks/bench.py run --cases captain-retakes --arms claude-base --runs 1 --run-id smoke-claude --max-cost-usd 15`
- Versions: Claude Code 2.1.311, t3 v0.1.5, shippy be46df1
- Models: claude-base = claudeAgent `claude-opus-5-5` (provider default effort); judge `claude-sonnet-5-5`
- Summary:

| Arm | n | Resolved | Hidden pass | Suite green | Wall (min) | Cost ($) | Tokens | Judge | Hygiene issues |
|---|---|---|---|---|---|---|---|---|---|
| oracle | 6 | 100% | 100% | 100% | - | 0 | 0 | - | 0 |
| null | 6 | 0% | 31% | 0% | - | 0 | 0 | - | 0 |
| claude-base (captain-retakes) | 1 | 0% | 85% (28/33) | 0% | 4.0 | 1.06 | 1,194,606 | 4/10 | 1 |

- Notes:
  - All 6 cases pass the control check (oracle resolved, null unresolved). Java nulls report 0/0 because compilation fails, as intended.
  - claude-base finished both turns with no questions in 240 s. It made 3 Conventional commits, and all 3 carry attribution lines added by the harness. Opus tokens: 42 input, 19,022 output, 1,118,346 cache read, 57,196 1h cache write.
  - The judge cost $0.07 and is not part of arm cost.
  - Not run: codex-base, shippy, shippy-t3 (free T3 models on cooldown; antigravity/gemini pool exhausted until about 2026-11-17).
