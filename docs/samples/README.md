# Sample outputs

The [cases directory](cases/) holds three case files produced by real `/investigate` runs on the synthetic bank.

| Case | Scenario | Risk rating | Suggested action |
| --- | --- | --- | --- |
| [C-001](cases/C-001.json) | Planted sanctions case | High | Escalate |
| [C-016](cases/C-016.json) | Innocent cash-business look-alike | Medium | Request more information |
| [C-019](cases/C-019.json) | Multi-day demo pattern from the daily pipeline | Medium | Request more information |

[usage.sample.jsonl](usage.sample.jsonl) contains the usage rows for C-001 and C-019: one row for the main run and one for each subagent. The rows for the C-016 run were not kept. Local transcript paths have been replaced with `<local transcript>`. See the [scorecard](../../eval/scorecard.md) for evaluation results. All case data and bank records are synthetic.

## Regenerate the samples

Generate the bank and run the rules. Follow the investigation steps for C-001 in the agent README, then run `/investigate C-016` in the same way. [Agent README](../../agent/README.md)

Generate and process the 16, 17 and 18 November 2026 batches in order with the agent enabled. The third batch creates C-019. [Pipeline README](../../pipeline/README.md)

Copy the three case files from `cases/`. Take the matching rows from `usage/usage.jsonl` and replace each transcript path in the `evidence` field with `<local transcript>`. Run `python eval/score.py` from the repository root to build the scorecard.
