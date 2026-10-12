# ML validation report

## Implementation summary

`ml/` implements four independent, CPU-only evidence components over the existing prepared-person and peer-group contracts:

1. Isolation Forest (`plfs-ml-v1.0`, feature spec `plfs-if-features-v1.0`), with fixed seed `20260925`, 25 trees, 1,024 rows/tree, and a deterministic 10,000-row fit cap per release/observation/design/visit/month boundary.
2. Peer-scoped LOF (`plfs-lof-features-v1.0`), using only the issued `day7_total_hours` peer assignments. Its numeric feature vector is age, day-7 hours, and log-transformed salaried/self-employed earnings. Fit references are deterministically capped at 1,000 valid peer members with up to 20 neighbours.
3. Two-fold, out-of-fold HistGradientBoosting conditional evidence (`plfs-conditional-features-v1.0`) for first-visit salaried earnings. It has 30 boosting iterations and never includes the target in its predictor matrix.
4. Blocked exact response-signature evidence (`plfs-exact-signature-v1.0`) over nine non-identifying response values. It does not implement non-exact similarity.

Each method writes its own Parquet file. No evidence values are combined, averaged, thresholded into actions, or represented as an error probability.

## Test results

Command:

```powershell
python -m pytest -q preprocessing/tests peer_groups/tests statistical/tests contextual/tests ml/tests
```

Result: **31 passed** in 14.21 seconds. One non-failing environment warning was emitted by joblib because Windows physical-core discovery is unavailable in this environment. ML tests cover feature exclusions (including weights), missing/non-numeric inputs, categorical encoding, leakage prevention, deterministic seeds and output, release/design separation, peer-only LOF, insufficient peer support, blocked signatures, provenance, and `NOT_ASSESSABLE` paths.

## Real-data validation runs

All paths below use the matching preprocessing run and issued peer-group run. The figures are coverage counts, not record-error counts.

| Release / route | Rows | Runtime | Isolation Forest | LOF | Conditional model | Exact-signature evidence |
|---|---:|---:|---:|---:|---:|---:|
| 2023–24 first visit | 418,159 | 143.694 s | 418,159 / 0 | 413,117 / 5,042 | 418,159 / 0 | 418,159 / 0 |
| 2023–24 revisit | 504,440 | 135.326 s | 504,440 / 0 | 0 / 504,440 | 0 / 504,440 | 504,440 / 0 |
| Calendar 2024 first visit | 415,549 | 140.538 s | 415,549 / 0 | 410,877 / 4,672 | 415,549 / 0 | 415,549 / 0 |
| Calendar 2025 first visit | 1,148,634 | 472.572 s | 1,148,634 / 0 | 1,079,016 / 69,618 | 1,148,634 / 0 | 1,148,634 / 0 |

Numbers are `ASSESSABLE / NOT_ASSESSABLE` after the method name. Run directories:

- `ml/runs/2023_24_first_visit_2023_24_first_v1`
- `ml/runs/2023_24_revisit_2023_24_revisit_v1`
- `ml/runs/2024_first_visit_2024_first_v1`
- `ml/runs/2025_first_visit_2025_first_v1`

LOF used 1,679 peer groups for 2023–24 first visit (issued sizes 30–8,196), 1,677 for Calendar 2024 (30–8,203), and 7,530 for Calendar 2025 (30–2,863). Large issued groups use the documented deterministic 1,000-row LOF fit reference cap. Revisit is explicitly `NOT_ASSESSABLE` for LOF because it has no issued day-7-hours peer target and for the conditional model because the V1 contextual day-7-hours predictor is unavailable; it is not silently treated as normal.

Exact-pattern result counts were 35,032 records (2023–24 first visit), 35,272 (revisit), 34,289 (Calendar 2024), and 125,937 (Calendar 2025). These are records sharing a blocked response signature, not duplicate declarations. Their emitted wording is “Repeated/highly similar response pattern requiring verification.”

The 2025 monthly run was streamed boundary-by-boundary to keep peak memory bounded. A roughly 2.1 GB peak was observed in this Windows environment; the final runtime includes all four components.

## Reproducibility

An independent Calendar 2024 repeat was run in `ml/runs/2024_first_visit_2024_first_repro_v1`. After deterministic sort by `source_observation_id`, all four evidence outputs matched exactly across 415,549 records: identifiers, method and feature metadata, assessability fields, raw model scores, ranks, predictions/deviations, signatures, and reference fields. Stochastic settings are explicit in `config.py` and run metadata.

## Known limitations and unresolved dependencies

- There are no confirmed ML error labels. Scores are anomaly/deviation evidence only, with no calibration, probability-of-error interpretation, or error classification.
- The prepared data does not provide a reviewed field-level applicability mask. Required absent or non-numeric ML values are handled conservatively as missing/not assessable where necessary.
- The conditional model is limited to first-visit salaried earnings. It does not provide categorical model outputs and does not support revisit under this V1 feature contract.
- LOF is limited to the existing first-visit day-7-hours peer assignment. It does not construct a new revisit peer definition.
- High-similarity (non-exact) detection is **NOT IMPLEMENTED**. A defensible public-data distance metric and threshold require separate approval and evaluation; V1 uses only safe blocking plus exact signatures.
- Isolation Forest uses a deliberately modest deterministic CPU budget. It is evidence-generation, not an exhaustive anomaly-discovery claim.
- Next dependency: reviewed PLFS applicability/code-list metadata and confirmed-review outcomes are needed before any calibrated conditional probabilities, error-rate evaluation, or future fusion/influence stage can be considered.
