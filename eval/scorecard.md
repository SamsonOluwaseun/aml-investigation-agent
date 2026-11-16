# Evaluation scorecard
Generated on: 2026-11-16
Data is entirely synthetic.

Coverage: investigated 3 of 19 open alerts; 3 case files.
Suspicious planted cases: 15 alerted; 1 investigated; 15 in answer key. 1 caught.
Look-alikes: 3 alerted; 1 investigated; 12 in answer key.

## Measures

| Measure | Result | Target | Met |
| --- | --- | --- | --- |
| Catch rate | 1/15 | >= 13/15 | partial |
| False alarms | 0 | <= 3 | yes |
| Citation check | 121/121 (100.0%) | 100% | yes |
| Right typology | 1/15 | >= 12/15 | partial |
| Tokens per case | mean 175,893.5; median 175,893.5 (2 cases with usage) | Record and reduce | recorded |
| Handoff amplification | See per-case lines | Record per case | recorded |

## Per case

- C-001: planted suspicious; planted typology high_risk_link; risk_rating High; suggested_action Escalate; caught yes; right typology yes; 179,028 tokens; top-level 102,393; amplification 1.748x
- C-016: look-alike; planted typology structuring; risk_rating Medium; suggested_action Request more information; not a false alarm; no usage logged
- C-019: not in answer key; risk_rating Medium; suggested_action Request more information; not scored; 172,759 tokens; top-level 100,669; amplification 1.716x

## Notes

- Catch rate and right typology are partial: fewer than all 15 planted suspicious cases have case files.
- Citation check verifies record existence only, not whether a record supports a claim.
- Token costs are API-equivalent. Cases without usage rows are labelled no usage logged and excluded from token statistics.
- Token mean and median include only IDs with usage rows, including usage-only cases; amplification is unavailable without positive top-level investigate tokens.
- Targets are demo starting points.
- Met is recorded for recording-only measures, which have no numeric pass target.
