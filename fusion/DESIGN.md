# Fusion and the supervisor queue — design (`MoSPI-fusion-v2.1-lanes`)

Status labels: **Validated** (checked against official documents or published magnitudes), **Evaluated** (measured on controlled injected errors), **Implemented, not evaluated**, **Provisional** (engineering default pending HSD input), **Not assessable**.

## Why the V2.0 construction was replaced (in place)

V2.0 ranked every source within the run, averaged the ranks with fixed weights, let the highest of three ML ranks override the average, and multiplied the result by a State × sector share-of-total influence. The audit in `docs/10_10_IMPROVEMENT_PLAN.md` §5.7 measured that this (a) diluted value errors that only one or two sources can see, (b) let Isolation Forest — near chance on its own — dominate through the max and the override, (c) let contextual surprisal, which grows with group size, add noise, and (d) over-reviewed the smallest UTs (CRITICAL share 20.4% in Lakshadweep against 1.15% in Uttar Pradesh). It was replaced, not retuned. `fusion/legacy.py` keeps it only as evaluation baseline A0; stored V2.0 runs stay readable and are labelled "superseded method" in the workspace.

## Boundary

Fusion consumes, never reruns, the evidence layers. It requires the statistical, contextual, ML (conditional models), historical and integrity runs; the pattern run is optional. Every run must agree on release, observation, design period and preparation run (strict provenance gate). Inputs from a stage that predates its current method version fail loudly with the missing column named. Nothing is an error probability.

## Lanes (plan §8.1)

| Lane | Evidence | Where it goes |
|---|---|---|
| Rules | Approved hard integrity rules, person and household level (`integrity/`) | Always "Check now"; never mixed into a score. Household findings are household cases. Soft (warning) rules go to "Check if time". |
| Value | Per variable (salaried earnings, self-employment earnings, day-7 hours, day-7 casual wage): `p_cur` current peers (leave-one-out), `p_hist` earlier periods (out-of-sample), `p_model` expected-value model trained on earlier periods (split-conformal) | `p_ref = mean(p_cur, p_hist)`; `p_v = Šidák(min(p_ref, p_model), mechanisms)`; record `value_p = Šidák(min_v p_v, variables assessed)` (`fusion/lanes.py`) |
| Coding | Conformal frequency tail probability of the occupation code within its comparison group (`contextual/`) | Own small share of the budget |
| Group (FSU) | Cauchy combination of the FSU's checks, Benjamini–Hochberg across FSUs (`pattern/fsu_summary.parquet`) | Group alerts and case context only; never moves a case |
| Research only | Isolation Forest, LOF | Not read by fusion |

All inputs are tail probabilities with a fixed meaning ("fewer than 1 in N comparable records look like this"), not within-run ranks, so a quiet batch gives a short list. Their finite-sample floors (about 1/n) mean a small comparison group cannot produce overwhelming evidence — by design. Averaging `p_cur` and `p_hist` is conservative when the two references agree; whether the combined values are calibrated on real data is reported by every run (burden check below) and is to be tested in the evaluation stage. **Implemented, not evaluated.**

## Queue (plan §8.3; `fusion/queue.py`)

* Review budget: 1% of the batch's records (**Provisional** default until HSD supplies supervisor capacity), 10% of it reserved for coding checks, at most 10 value checks per FSU in "Check now".
* Threshold of a lane = its budget ÷ the records it can assess (plan §8.3, capacity ÷ records), so with calibrated evidence the expected number of alerts among clean records equals the budget. A case passing the threshold enters "Check now" strongest-first until the budget or FSU cap is reached; overflow and the next band of evidence (5 × threshold, up to 2 × budget) go to "Check if time".
* Within a tier: rules first, then impact, then evidence. Impact never changes the tier.
* `priority_band` ∈ CHECK_NOW, CHECK_IF_TIME, NOT_FLAGGED, NOT_ASSESSABLE; `queue_position` is the global order; `priority_score` is a monotone transform of it (kept for API ordering).

## Impact (plan W2.7; `fusion/impact.py`)

`impact_se = |w_i (y_i − m_i) / Σ_d w| / SE_d`: the change in the domain's weighted mean (release × period × State/UT × sector, applicable persons) if the value were replaced by its expected value, in design-based standard errors (Taylor linearisation, FSU as PSU within strata), with the SE floored at the national CV × domain mean. Small domains have large SEs, so the same relative error does not automatically score higher there. Final weights: `MULT/100`, or `/200` when NSS ≠ NSC (pre-2025 READMEs); `MULT/100` (2025) — **Validated**.

## Burden check on real data (plan §12.6)

Every fusion report states the nominal number of value alerts per 1,000 records if all records were clean and the evidence calibrated (threshold × 1,000 × assessable share), the observed number on the batch, and the highest/median State "Check now" rate. Released files are post-scrutiny, so a large excess indicates a calibration problem, not a data problem. This is a structural check, not validation.

## Outputs

`fused_cases.parquet` (person and household cases with lanes, tier, queue position, impact, FSU context), `value_evidence.parquet` (every per-variable tail probability and the stored values it came from, read by the case page), `impact_domains.parquet`, `evidence_cards.parquet` (queued cases), `group_priorities.parquet`, `fusion_report.json/.md`, `run_metadata.json`, and the append-only, hash-chained `review_audit.sqlite`.

## Decisions and feedback

Decisions use the taxonomy confirmed error / valid but unusual / needs field verification / cannot verify / escalate, each with a reason code, how it was verified, an optional corrected item and value, and time on case (`fusion/review.py`). `fusion/feedback.py` turns decisions into per-lane confirmed-error shares with Wilson intervals and may *propose* a threshold change; nothing is applied automatically.
