# Statistical Evidence Layer validation report

## 1. Executive status

**READY.** The approved V1 implementation was validated against all supplied PLFS prepared datasets. The complete relevant test suite passed, the four required operational paths completed, all required finite fields were finite, peer metadata reconciled with reconstructed reference populations, the post-2025 month boundary was retained, and the final revisit output contains no `PENDING_CHANGE_REFERENCE` status.

No statistical methodology was added or changed. V1 remains limited to `cws_earnings_salaried`, `cws_earnings_self_employed`, and `day7_total_hours`, with empirical midrank percentiles, linear quantiles, MAD evidence, explicit zero-MAD handling, explicit missingness and `NOT_ASSESSABLE`, and Release-1-only revisit evidence.

## 2. Implementation reviewed

Reviewed: `statistical/engine.py`, `statistics.py`, `revisit.py`, `config.py`, `cli.py`, `reporting.py`, `DESIGN.md`, `README.md`, and `statistical/tests/`; `preprocessing/` and its tests/runs; and `peer_groups/` and its tests/runs.

The final correction is present in `statistical/revisit.py`: candidates whose linked revisit-change reference group is smaller than the configured minimum (30) receive:

```text
revisit_comparison_status = NOT_ASSESSABLE
revisit_assessability_reason = REVISIT_CHANGE_REFERENCE_GROUP_BELOW_MINIMUM
```

The implementation may transiently form `PENDING_CHANGE_REFERENCE` while it counts the candidate population, but it resolves every candidate before output. No final operational output contains that value.

The review also confirmed that the engine preserves release, observation, design-period, visit, and (for 2025) month boundaries; does not use survey weights as a statistical predictor; does not produce an error probability, anomaly/error label, ML result, contextual model, fusion, or priority output.

## 3. Tests

Command:

```powershell
python -m pytest -q preprocessing/tests peer_groups/tests statistical/tests
```

| Total | Passed | Failed | Skipped | Runtime |
|---:|---:|---:|---:|---:|
| 15 | 15 | 0 | 0 | 5.32 s |

The suite includes preprocessing, peer-group, and statistical tests. A regression test was added for the final correction: an otherwise eligible linked revisit change with a below-minimum change-reference group is `NOT_ASSESSABLE`, carries `REVISIT_CHANGE_REFERENCE_GROUP_BELOW_MINIMUM`, and has no `PENDING_CHANGE_REFERENCE` status.

## 4. Real-data inputs and operational runs

| Validation path | Prepared input / peer input | Release, observation, design | Month handling | Final output directory | Runtime |
|---|---|---|---|---|---:|
| 2023-24 first visit | `final_2023_24_first` / `2023_24_first_v1` | `2023_24`, first visit, `pre_2025` | blank pre-2025 month boundary | `statistical/runs/2023_24_first_visit_post_fix_validation_20260924_2023_24_first_with_revisit` | 92.022 s |
| 2023-24 revisit companion | `final_2023_24_revisit` / `2023_24_revisit_v1`, linked to the preceding first-visit input | `2023_24`, revisit V2-V4, `pre_2025` | no month pooling | `statistical/runs/2023_24_first_visit_post_fix_validation_20260924_2023_24_first_with_revisit/revisit_statistical_evidence.parquet` | included above |
| 2024 first visit | `final_2024_first` / `2024_first_v1` | `2024`, first visit, `pre_2025` | blank pre-2025 month boundary | `statistical/runs/2024_first_visit_post_fix_validation_20260924_2024_first` | 121.064 s |
| 2025 first visit | `final_2025_first` / `2025_first_v1` | `2025`, first visit, `post_2025` | mandatory calendar-month boundary; months 1-12 retained | `statistical/runs/2025_first_visit_post_fix_validation_20260924_2025_first` | 299.276 s |

The revisit operation is correctly implemented as the Release-1 companion output of the 2023-24 first-visit run. It uses the supplied revisit prepared data and revisit peer-group run, rather than fabricating an independent first-visit/revisit mix.

## 5. 2023-24 first-visit post-fix result

Processing: 1,254,477 target rows; 1,241,193 assessable (98.9411%); 13,284 `NOT_ASSESSABLE`. Each target had 418,159 rows, 413,731 assessable, and 4,428 not assessable. All non-assessability was `PEER_NO_CONFIGURED_GROUP_MEETS_MINIMUM`; raw blank, nonnumeric, and non-finite target counts were zero for all three targets. Peer assignment coverage was 413,731 rows per target.

| Target | Peer groups | Zero-MAD groups | Valid robust deviations | Null robust deviations from zero MAD | Non-finite robust deviations |
|---|---:|---:|---:|---:|---:|
| `cws_earnings_salaried` | 2,976 | 2,141 | 413,731 | 0 | 0 |
| `cws_earnings_self_employed` | 2,976 | 2,031 | 413,681 | 50 | 0 |
| `day7_total_hours` | 1,714 | 929 | 397,308 | 16,423 | 0 |

Percentile summaries (`min / p05 / p25 / median / p75 / p95 / max`):

| Target | Percentile summary |
|---|---|
| `cws_earnings_salaried` | 0.0002783964 / 0.4393939394 / 0.5 / 0.5 / 0.5 / 0.5357142857 / 0.9995531725 |
| `cws_earnings_self_employed` | 0.0004508566 / 0.2624633431 / 0.5 / 0.5 / 0.5 / 0.6925232919 / 0.9995938262 |
| `day7_total_hours` | 0.0011627907 / 0.1159900580 / 0.5 / 0.5 / 0.5 / 0.8475609756 / 0.9997905320 |

All assessable required fields, tail-distance fields, and percentiles were finite; all percentile values were in `[0, 1]`; tied values had one identical midrank percentile per peer group/value; and reconstructed peer population sizes exactly matched peer metadata. No calculated evidence was present on a not-assessable row. Observed ranges included salary up to 300,000, self-employed earnings from -30,000 through 500,000, and hours 0 through 20. The 29 negative self-employed earnings were retained numerically unchanged.

## 6. 2023-24 revisit result

The companion table has 1,513,320 target records: 504,440 physical revisit records multiplied by the three approved targets. Revisit-round coverage is 170,054 V2, 167,594 V3, and 166,792 V4 physical records. Every assessed change group was visit-specific; no peer group crossed a revisit round.

| Target | Records | Linked first visits | Unmatched | Assessable changes | `NOT_ASSESSABLE` |
|---|---:|---:|---:|---:|---:|
| `cws_earnings_salaried` | 504,440 | 253,527 | 250,913 | 246,430 | 258,010 |
| `cws_earnings_self_employed` | 504,440 | 253,527 | 250,913 | 246,430 | 258,010 |
| `day7_total_hours` | 504,440 | 0 | 504,440 | 0 | 504,440 |
| **All targets** | **1,513,320** | — | — | **492,860** | **1,020,460** |

Reason distribution across the complete revisit output:

| Reason | Records |
|---|---:|
| assessable (null reason) | 492,860 |
| `NO_VALID_LINKED_FIRST_VISIT` | 501,826 |
| `REVISIT_CHANGE_REFERENCE_GROUP_BELOW_MINIMUM` | 7,680 |
| `REVISIT_PEER_NOT_ASSESSABLE` | 6,514 |
| `REVISIT_TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION` | 504,440 |

All 1,850 assessable linked-change reference groups had at least 30 members; the minimum was exactly 30. The 7,680 below-minimum linked-change records (3,840 for each earnings target) are explicitly `NOT_ASSESSABLE`. `PENDING_CHANGE_REFERENCE` appears **0 times** in the final output.

`day7_total_hours` is unavailable for the revisit source profile. All 504,440 rows carry `REVISIT_TARGET_UNAVAILABLE_FOR_RELEASE_OBSERVATION`; first/revisit values and signed change are null. Therefore no hours comparison was fabricated. For assessed earnings changes, signed change, change percentile, change median, and change MAD were finite. No numeric output contained infinity.

## 7. 2024 first-visit result

Processing: 1,246,647 target rows; 1,234,032 assessable (98.9881%); 12,615 `NOT_ASSESSABLE`. Each target had 415,549 rows, 411,344 assessable, and 4,205 not assessable. The only not-assessable reason was `PEER_NO_CONFIGURED_GROUP_MEETS_MINIMUM`; blank, nonnumeric, and non-finite raw target counts were all zero. Peer assignment coverage was 411,344 per target.

| Target | Peer groups | Zero-MAD groups | Valid robust deviations | Null robust deviations from zero MAD | Non-finite robust deviations |
|---|---:|---:|---:|---:|---:|
| `cws_earnings_salaried` | 2,965 | 2,135 | 411,327 | 17 | 0 |
| `cws_earnings_self_employed` | 2,965 | 2,024 | 411,299 | 45 | 0 |
| `day7_total_hours` | 1,706 | 921 | 395,219 | 16,125 | 0 |

| Target | Percentile summary: min / p05 / p25 / median / p75 / p95 / max |
|---|---|
| `cws_earnings_salaried` | 0.0002808200 / 0.4361702128 / 0.5 / 0.5 / 0.5 / 0.5476190476 / 0.9996003197 |
| `cws_earnings_self_employed` | 0.0003972984 / 0.2644836272 / 0.5 / 0.5 / 0.5 / 0.6916666667 / 0.9997978164 |
| `day7_total_hours` | 0.0011682243 / 0.1184210526 / 0.5 / 0.5 / 0.5 / 0.8477611940 / 0.9998406120 |

All percentile, required finite, tied-value, peer-size consistency, and zero-MAD checks passed. The data include salary through 520,000, self-employed earnings from -10,000 through 500,000, and hours through 20 without overflow; all four negative self-employed values were unchanged. The output is first-visit only and correctly has no revisit table.

## 8. 2025 first-visit result

Processing: 3,445,902 target rows; 3,252,540 assessable (94.3886%); 193,362 `NOT_ASSESSABLE`. Each target had 1,148,634 rows, 1,084,180 assessable, and 64,454 not assessable. The only not-assessable reason was `PEER_NO_CONFIGURED_GROUP_MEETS_MINIMUM`; blank, nonnumeric, and non-finite raw target counts were all zero. Peer assignment coverage was 1,084,180 per target.

| Target | Peer groups | Zero-MAD groups | Valid robust deviations | Null robust deviations from zero MAD | Non-finite robust deviations |
|---|---:|---:|---:|---:|---:|
| `cws_earnings_salaried` | 11,201 | 8,958 | 1,084,161 | 19 | 0 |
| `cws_earnings_self_employed` | 11,201 | 8,171 | 1,084,166 | 14 | 0 |
| `day7_total_hours` | 7,835 | 4,669 | 1,041,235 | 42,945 | 0 |

| Target | Percentile summary: min / p05 / p25 / median / p75 / p95 / max |
|---|---|
| `cws_earnings_salaried` | 0.0008818342 / 0.46875 / 0.5 / 0.5 / 0.5 / 0.5444444444 / 0.9991166078 |
| `cws_earnings_self_employed` | 0.0005291005 / 0.2916666667 / 0.5 / 0.5 / 0.5 / 0.7032526356 / 0.9996894410 |
| `day7_total_hours` | 0.0006858711 / 0.1237623762 / 0.5 / 0.5 / 0.5 / 0.8583333333 / 0.9997275204 |

All 12 calendar months are present and remain separate. There are **0** assigned peer groups whose members span more than one month. The output contains only `2025` / `first_visit` / `post_2025` / V1 rows; it cannot pool with either pre-2025 release. All percentile, tied-value, finite-required-field, peer-size reconciliation, and zero-MAD checks passed. Values included salary through 500,000, self-employed earnings from -30,000 through 710,000, and hours through 20 without overflow; all nine negative self-employed earnings were unchanged. The output is first-visit only and correctly has no revisit table.

## 9. Statistical sanity checks

The following checks passed on every applicable final output:

- Percentiles were finite and in `[0, 1]`; tied values had identical empirical-midrank treatment within a peer group.
- Linear `.05/.25/.50/.75/.95` quantiles, median, and MAD were finite wherever statistics were required.
- No NaN/Inf occurred in required finite fields; the only null robust deviations were the explicit zero-MAD/non-median case. No division-by-zero substitute was introduced.
- No statistic was populated for a `NOT_ASSESSABLE` first-visit peer row.
- The reconstructed reference population size equalled `peer_group_size` for every assessable row; minimum assessable size was 30 in all runs.
- Negative self-employed earnings were preserved; large observed values completed with no overflow.
- First visits and revisits were separated by their source profile and visit boundary. Pre-2025 and post-2025 records were not mixed. 2025 peer groups had no cross-month membership.
- Revisit comparisons occurred only for valid first/revisit links; hours had no revisit evidence.
- Code review and schemas confirmed no survey-weight predictor, error probability, or automatic error label.

## 10. Reproducibility

Two fresh calculations were executed with the same real inputs, peer runs, and parameters:

- `statistical/runs/2024_first_visit_post_fix_validation_reproducibility_20260924_2024_first`
- `statistical/runs/2023_24_first_visit_post_fix_validation_reproducibility_20260924_2023_24_first_with_revisit`

For 2024, a deterministic every-997th-row sample of 1,251 records matched exactly for source/target identity, percentile, median, all five quantiles, MAD, robust deviation, and assessability fields.

For 2023-24, the corresponding 1,259-row cross-sectional sample and 1,518-row revisit sample matched exactly. The revisit comparison included linkage, first/revisit values, signed/absolute/relative change, status/reason, change reference group, percentile, median, five quantiles, MAD, and robust deviation. The rerun also had zero `PENDING_CHANGE_REFERENCE` values.

**Reproducibility: PASS.** Timestamps and run IDs were deliberately excluded from comparison.

## 11. Pre-fix versus post-fix distinction

Historical artifact:

```text
2023_24_first_visit_2023_24_first_v1_memory_bounded
Status: PRE-FIX / historical validation artifact
```

Post-fix operational artifacts:

```text
2023_24_first_visit_post_fix_validation_20260924_2023_24_first_with_revisit
2024_first_visit_post_fix_validation_20260924_2024_first
2025_first_visit_post_fix_validation_20260924_2025_first
```

The historical and post-fix 2023-24 cross-sectional `statistical_evidence.parquet` tables have the same 1,254,477 rows, same columns, and are exactly equal field-for-field. This verifies that the revisit correction did not alter first-visit statistics.

The historical report recorded 7,680 `PENDING_CHANGE_REFERENCE` revisit rows. The post-fix report records those 7,680 rows as `NOT_ASSESSABLE` with `REVISIT_CHANGE_REFERENCE_GROUP_BELOW_MINIMUM`; final `PENDING_CHANGE_REFERENCE` count is zero.

## 12. Runtime and performance

Primary run times were 92.022 s (2023-24 first/revisit companion), 121.064 s (2024), and 299.276 s (2025). The largest run processed 3,445,902 target rows without changing the month boundary or reducing the approved peer minimum.

An incomplete duplicate retry directory, `statistical/runs/2023_24_first_visit_post_fix_validation_retry_20260924_2023_24_first_with_revisit`, was created while a terminal-detached operation was still completing and was explicitly stopped to avoid overlapping resource use. It is retained for traceability and is not a result. The primary post-fix 2023-24 run had already completed successfully; no final result was overwritten or deleted.

## 13. Issues found and fixed

| Item | Resolution |
|---|---|
| The final below-minimum revisit status was not directly asserted by the prior test suite. | Added a regression test. It passes and confirms output resolution to `NOT_ASSESSABLE`, not pending. |
| The new regression test initially exposed a test-helper duplicate-argument error. | Corrected the helper’s parameter forwarding. No production statistical code or methodology was changed. |
| Terminal execution can detach long-running child processes. | The redundant overlapping retry was stopped and retained as incomplete; final primary runs and independent reproducibility reruns completed successfully. |

There are no unresolved implementation errors and no identified methodological issue.

## 14. Remaining limitations

These are approved V1 boundaries, not validation failures: univariate peer-conditioned evidence does not determine correctness; zero-MAD/non-median observations cannot receive a finite robust deviation; revisit evidence is limited to valid 2023-24 Release-1 links; and calendar-2024/2025 first-visit data have no approved revisit path. The layer remains unweighted and intentionally has no contextual/probabilistic model, ML, fusion, prioritisation, or automatic decision label.

## 15. Final readiness decision

**READY.** All 15 relevant tests pass; all four required real-data paths completed; post-fix first-visit statistics were rerun and proved unchanged; the required 2023-24 revisit evidence completed; 2024 and 2025 first-visit outputs completed; finite/peer-size/boundary/revisit checks passed; `PENDING_CHANGE_REFERENCE` is absent from final operational output; reproducibility passed; and the required output files and this report exist.

The Statistical Evidence Layer is ready to be consumed by the Contextual/Probabilistic Layer.
