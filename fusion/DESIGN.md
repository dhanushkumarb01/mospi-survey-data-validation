# Fusion / evidence combination — V2 design (`MoSPI-fusion-v2.0`)

Status labels: **Validated** (checked against official documents or published magnitudes), **Evaluated** (measured on controlled injected errors), **Provisional** (engineering choice, not learned from confirmed PLFS errors), **Not assessable**, **Not implemented**.

## Boundary

Fusion consumes, but never reruns, the evidence layers. A missing or non-assessable source is excluded from risk, never converted to low/zero evidence. It never declares a record wrong or estimates an error probability.

## Strict provenance gate

The prepared-person metadata and every supplied run (statistical, contextual, ML, and optionally pattern, historical, integrity) must agree on `release`, `observation`, `design_period` and the preparation `run_id`. Evidence IDs must map to the supplied prepared persons. No release pooling, no month or design-break crossing.

## Two kinds of evidence, kept apart (V2)

| Level | Sources | Used for |
|---|---|---|
| Record | statistical, contextual, ML, historical; documented integrity rules | record risk and priority |
| Group (FSU) | pattern | FSU context on the case page; separate FSU queue |

V1 inherited each FSU's strongest pattern rank into every member's risk, and the extreme-rank override then lifted 1,974 records (2024) to the top of the list on FSU evidence alone (audit H3). In V2 pattern evidence has **no weight in record risk and cannot trigger the override**. Membership of an unusual FSU is shown as context ("the FSU as a whole differs…, not evidence about this person") and only when an FSU check is notable after multiple-testing correction.

## Source scores and calibration (Provisional)

| Source | Stored input |
|---|---|
| Statistical | max over applicable assessable targets of `2·|percentile − 0.5|` (statistical layer's own assessability, which excludes questionnaire placeholders) |
| Contextual | conditional-frequency surprisal of the occupation code |
| ML | max of the stored method evidence ranks (Isolation Forest, LOF, conditional model; exact-signature evidence is informational) |
| Historical | max over targets of `2·|past-period percentile − 0.5|` |

Each is converted to a within-run empirical mid-rank. For statistical evidence an exact 0 (value equal to its comparison-group median) is "no evidence" and gets rank 0; in V1 a large tie block of such zeros received a rank of about 0.3 (audit M4).

`risk = weighted mean of available record-level ranks` with provisional weights statistical 0.30, contextual 0.20, ML 0.25, historical 0.25; `risk = max(risk, highest record-level rank)` when that rank ≥ 0.995 (provisional override). A record breaking an error-severity documented integrity rule is listed first (`priority_score = 1`): it is a definite inconsistency in the recorded answers, although the schedule still decides which answer is wrong.

## Influence — potential effect on a weighted total (Provisional)

V1 used `design weight × max |observed − peer median|` across rupee and hour targets, which has no meaning across units (audit H2). V2 uses the selective-editing local score (Latouche & Berthelot 1992; Hedlin 2003), **per variable**:

`local_score_t = w · |y_t − m_t| / Σ_{j∈d} w_j · |y_jt|`

* `w`: documented final weight for a quarterly (pre-2025) or monthly (2025) estimate — `MULT/100`, or `MULT/200` when NSS ≠ NSC (pre-2025 READMEs); `MULT/100` (README2025). Validated against the READMEs; national indicators computed with it match published PLFS magnitudes.
* `m`: the stored comparison-group median, used as the anticipated value.
* `d`: release × quarter/month × State/UT × sector; the denominator includes only persons to whom the item applies.

Each score is a share of a weighted domain total, so rupee and hour scores are comparable as shares. `raw_influence` = the largest share; `influence_score` its within-run rank. It is **not** the impact on an official LFPR/WPR/UR estimate: the anticipated value, domain and choice of "total" are not HSD-approved. Records with no applicable value, no stored anticipated value or no weight are `NOT_ASSESSABLE` (not zero), so they receive no priority.

`priority = risk × influence`; bands CRITICAL ≥ 0.8, HIGH ≥ 0.5, MEDIUM ≥ 0.2, LOW ≥ 0 (Provisional; with two roughly independent ranks the top band holds about 2% by construction). Bands order work; they are not levels of error likelihood. There is no validated review cut-off.

## FSU group queue

`group_priorities.parquet`: per FSU, the minimum Benjamini–Hochberg q-value over its pattern checks, the number of notable checks, and `group_priority_score = −log10(min q)`; bands HIGH (q < 0.01, "clear group difference"), MEDIUM (q < 0.05), LOW. Group alerts never name an enumerator (no enumerator ID exists).

## Evaluation (Evaluated)

`evaluation/` injects controlled errors into a State subset and recomputes E0–E7 from the stored source scores; results are in `evaluation/results/` and on the Technical reference page. See `evaluation/README.md`.

## Outputs

`fused_cases.parquet`, `evidence_cards.parquet` (top 10,000; others rendered on demand), `group_priorities.parquet`, `influence_components.parquet` (per-variable local scores and domain totals), `fusion_report.json/.md`, `run_metadata.json`, append-only `review_audit.sqlite`.
