# MoSPI fusion report (MoSPI-fusion-v2.2-lanes)

- Fusion run: `demo`; release / observation: `2024` / `first_visit`
- Preparation run: `synthetic-prep`
- Review budget: 0.01 of records = 12 cases (default until HSD supplies capacity)

## Queue

| Tier | Cases |
|---|---:|
| NONE | 852 |
| NOT_ASSESSABLE | 287 |
| B | 13 |
| A | 1 |

## Real-data burden check (not a validation)

- Value-check threshold: 0.011560693641618497
- Nominal alerts per 1,000 records if every record were clean and the tail probabilities calibrated: 8.68
- Observed on this (released, post-scrutiny) batch: 0.00
- Max / median State "Check now" rate: None
- Discrete-test (Tarone) correction: True

## Interpretation boundary

Evidence is a tail probability ("this is rare for comparable people"), never a probability that an answer is wrong. Rule findings
are definite inconsistencies in the recorded answers. Impact orders cases within a tier and never changes which tier a case is in.
FSU alerts describe a group and never move a record. Isolation Forest and LOF are research outputs and are not read. Thresholds,
budget and lane shares are provisional engineering settings; the evaluation stage (docs/10_10_IMPROVEMENT_PLAN.md §12) has not been run.
