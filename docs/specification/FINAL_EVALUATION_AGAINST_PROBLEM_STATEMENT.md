# Final evaluation against the MoSPI problem statement

> **Historical document (5.5/10 baseline).** It evaluates the V2.0 priority construction (risk × influence), which has since been replaced in place by the lane design described in `fusion/DESIGN.md`. Its findings are the starting point of `docs/10_10_IMPROVEMENT_PLAN.md`; current status is recorded at the top of that plan.

**Subject:** the PLFS survey data validation platform in this repository (internal working name "MoSPI"; presented to users as the MoSPI survey data validation platform).
**Primary source of truth:** *A brief note from HSD, NSO, MoSPI — Design and Development of an Intelligent Survey Data Validation Platform using Probabilistic and Machine Learning Techniques* ("the brief").
**Secondary:** *Intelligent Survey Data Validation Platform — Research & Technical Documentation v1.0* ("the research document"). It elaborates the brief but is not the problem statement. Where it adds requirements, they are reported separately and never counted as requirements of the brief.
**Date:** 6 October 2026.
**Method:** every statement below was checked against the code and the real stored runs (DuckDB queries over the Parquet outputs, read-only), against the test suite, and against the running Docker deployment. Documentation was not accepted as evidence of implementation.

Labels used:
* **FULLY SATISFIED**, **PARTIALLY SATISFIED**, **NOT SATISFIED**
* **NOT ASSESSABLE**: required data or information is unavailable
* **FUTURE / ROADMAP ONLY**: documented, not implemented
* **NOT ESTABLISHABLE FROM THE AVAILABLE EVIDENCE**

---

## 0. Executive verdict

The platform is a carefully engineered, provenance-safe **evidence and review workbench** for PLFS first-visit person records. It does several things genuinely well:
* It respects survey design boundaries: release, visit, quarter/month and the January-2025 redesign.
* It applies questionnaire applicability and the documented final weights correctly.
* It compares each value with **earlier survey periods**.
* It explains every flag in plain language from stored numbers only.
* It records supervisor decisions in an audit trail with evidence snapshots.
* It now runs reproducibly in Docker.

It does **not yet demonstrate that it solves the brief's core problem**: helping supervisors find real anomalies and inconsistencies better than they do today. Three facts dominate:

1. **No real-error evidence exists, and none can exist from the supplied data.** The supplied PLFS files are the *released* unit-level data, already scrutinised and edited:
   * Documented integrity rules find **0 violations** in all three releases (415,549 / 418,159 / 1,148,634 persons).
   * Household size matches the person count in **every** household (101,957 / 101,920 / 270,472).
   * The audit stores contain **no supervisor decision** at all (only 22 "case viewed" events).

   Performance on raw eSigma/CAPI submissions, which is what supervisors actually scrutinise, is **NOT ESTABLISHABLE FROM THE AVAILABLE EVIDENCE**.
2. **In the project's own controlled study, the fused priority ranking is worse than its best single components on the errors that matter.** The headline "73.1 % precision in the top 1 %" (2024) is mostly the 600 injected rule breaches, which priority places first by construction and which CAPI already blocks. For the 1,773 injected errors that break no rule, the fused priority finds 10.3 % in the top 1 %. The statistical comparison alone finds 33.4 % and the historical comparison alone 35.2 %. 2025 shows the same pattern: 11.9 % against 31.3 % and 39.8 %. The fusion weights, override and bands are unvalidated engineering choices, and this evidence argues against the current settings.
3. **Several brief requirements are only partly met:**
   * Real-time API ingestion is **NOT SATISFIED**. There is a single-record check that stores nothing.
   * Validation against **related surveys** is **NOT ASSESSABLE**: no related survey data was supplied.
   * Enumerator bias is **NOT ASSESSABLE**: there is no enumerator identifier.
   * The integrity-check "facility" is a person-level YAML file with no referential or household rules that users can define.
   * Hands-on training material does not exist.

**Overall score: 5.5 / 10.** This is a credible foundation and a good decision-support prototype for within-design screening with historical comparison. It is not yet a validated intelligent validation platform, and not deployable on GoI infrastructure without the security work listed in §13. The breakdown is in §15.

---

## 1. What the brief actually asks for

The brief's problem statement, in its own words:

> "there is no mechanism at present to the supervisors to use the past data or related survey data for checking anomalies and inconsistencies"

and the existing CAPI checks

> "are insufficient to detect complex, contextual, or distributional anomalies such as enumerator bias, temporal drifts, unusual response patterns, or inconsistencies relative to historical trends or related surveys."

The required product is "a software tool for both online and offline validation of the survey data using probabilistic and machine learning based models on historical datasets to aid the HSD officials". It should be built first for PLFS but be general purpose, and may later be integrated in eSigma.

The core chain to be judged is therefore:

**survey data → validation → detection of unusual or inconsistent responses → use of historical or related information → statistical, probabilistic or ML analysis → prioritisation → explanation → supervisor review → decision → audit trail.**

---

## 2. Requirement → implementation matrix (the brief)

### 2.1 Background requirements

| # | Requirement (brief wording) | Status | Evidence in code/data | Gap | Required action |
|---|---|---|---|---|---|
| B1 | Supervisors can "use the past data … for checking anomalies" | **PARTIALLY SATISFIED** | `historical/engine.py`: each applicable earnings/hours value is compared with the same comparison cell in strictly preceding periods (up to 4 quarters pre-2025, 3 months in 2025). The comparison is shown on the case page ("Compared with earlier periods"), feeds risk (weight 0.25) and is filterable. 2024 run: 165,277 records have historical evidence. | Three variables only. Unweighted, nominal rupees. Pre-2025 history covers 6 quarters. 2025 compares only with earlier 2025 months (no pre-2025 history, by design). No model is trained on history and applied to new data. | Extend to more variables (status, occupation/industry mix) and, once approved, deflated earnings. |
| B2 | "… or related survey data" | **NOT ASSESSABLE** | No related survey (for example ASUSE, ASI, CPHS, Census) was supplied. No code compares with another survey. | Requirement unmet. | Obtain a related dataset with concept and reference-period mapping. Until then, report it as not assessable. The "general-purpose architecture" does **not** satisfy this. |
| B3 | Detect enumerator bias | **NOT ASSESSABLE** | No enumerator or investigator ID in any release. FSU is correctly **not** used as a proxy (`pattern/DESIGN.md`). | Unmet. | Needs the eSigma enumerator ID. |
| B4 | Detect temporal drifts | **PARTIALLY SATISFIED** | Area level: `historical` aggregate indicators (LFPR/WPR/UR, median earnings, mean hours by nation/State/district × sector × period) with change screening. 2024: 51 notable changes out of 2,913 assessable. FSU-level temporal drift has 0 assessable rows (each first-visit FSU is observed once). | Screening only: SRS standard errors without design effects, first-visit records only, seasonality not modelled. | Design-based SEs; seasonal comparison (same quarter of the previous year) once enough history exists. |
| B5 | Detect unusual response patterns | **PARTIALLY SATISFIED** | Record level: statistical, contextual, ML and historical layers. FSU level: G-test, Mann–Whitney and binomial tests with BH q-values. | The FSU queue is about 95 % "activity-status mix differs" (2024: 173 of 181 notable checks), which is largely genuine neighbourhood heterogeneity. The corrected FSU method has not been evaluated (§9). | Re-evaluate the corrected FSU checks; consider conditioning on stratum composition. |
| B6 | Inconsistencies relative to historical trends | **PARTIALLY SATISFIED** | As B1 and B4. | As B1 and B4. | As above. |
| B7 | Online **and** offline validation | **PARTIALLY SATISFIED** | Offline: the batch pipeline (`pipeline/run.py`). Online: `POST /api/validate/record` checks one submitted record against the documented rules and the stored comparison groups; nothing is stored. | The online path covers 10 fields, does no ML scoring and is not connected to any data source. | See F1. |
| B8 | PLFS first, but general purpose | **PARTIALLY SATISFIED** | Modular packages, immutable runs, a concept-based rule YAML. | PLFS column maps are hard-coded in Python (`preprocessing/config.py`, `peer_groups/config.py`, `ml/config.py`, `fusion/labels.py`, `fusion/explain.py`). A new survey needs code in at least 5 modules. | Metadata-driven survey configuration. |
| B9 | Future integration in eSigma | **FUTURE / ROADMAP ONLY** | `docs/ESIGMA_INTEGRATION_ROADMAP.md` (narrative). | No API contract or authentication design agreed with eSigma. | Objective 5 deliverable. |

### 2.2 Project objectives

| # | Objective | Status | Evidence | Gap |
|---|---|---|---|---|
| O1 | Modular, standalone platform capable of supporting multiple large-scale surveys | **PARTIALLY SATISFIED** | Standalone and modular; runs locally and in Docker. | Not survey-general (B8). |
| O2 | Probabilistic, statistical and ML methods on historical PLFS data, at record, cluster and aggregate levels | **PARTIALLY SATISFIED** | Record: robust statistics, conditional frequency, Isolation Forest, LOF, gradient-boosted conditional model, historical comparison. Cluster (FSU): tested evidence with q-values. Aggregate: weighted area indicators with change screening. | "Probabilistic" is limited to empirical conditional frequency and hypothesis-test p-values; there is no probabilistic model of the joint response. ML is fitted within the scored round, not on history. Cluster evidence is unevaluated in its current form. |
| O3 | Evaluate using PLFS 2024 onwards with defined measurement criteria | **PARTIALLY SATISFIED** | `evaluation/`: controlled injection, E0–E7, AP, ROC-AUC, P/R/F0.5/FPR at 1 %/5 %, recall by type, State and sector, for 2024 and 2025. | Synthetic errors only; the headline is inflated by rule injections; single seed, six States, no confidence intervals. The FSU results describe a superseded method. No real-error or expert evaluation (§9). |
| O4 | Hands-on training of HSD | **NOT SATISFIED** | No training material, guide or exercise exists. The UI's plain-language help is not training. | Training pack and supervised exercises. |
| O5 | Technical and architectural roadmap for eSigma integration | **PARTIALLY SATISFIED** | `docs/ESIGMA_INTEGRATION_ROADMAP.md`, `docs/DOCKER.md`. | No interface specification, data-exchange schema or security design agreed with eSigma. |

### 2.3 Required software features

| # | Feature | Status | Evidence | Gap / required action |
|---|---|---|---|---|
| F1 | Data ingestion in real time (through API) **and** periodic batch | **Batch: FULLY SATISFIED. Real time: NOT SATISFIED.** | Batch: `python -m pipeline.run --release …`, also in the Docker `batch` service; resumable, immutable runs, timing report. No endpoint accepts and stores survey records. `/api/validate/record` scores one record and **stores nothing**: it is an online check, not ingestion. | An ingestion API (authenticated, schema-validated, idempotent) plus incremental scoring. |
| F2 | Ability to develop statistical models and ML algorithms from historical data | **PARTIALLY SATISFIED** | Historical reference distributions are built from earlier periods. ML models are fitted per round with fixed seeds and recorded parameters. | No train-on-history / score-new-data separation for ML; no model registry or approval step. |
| F3 | Facility for defining integrity checks (referential, existential …) and executing them | **PARTIALLY SATISFIED** | `integrity/rules/plfs_person_rules.yaml`: 11 documented, cited rules; 6 rule types (`allowed_values`, `range`, `required_when`, `value_when`, `not_value_when`, `unique`); batch and single-record execution. Fixed structural checks in `preprocessing` cover key completeness (existential), code sets, duplicate keys and person→household linkage (referential). | Person level only. No household-level or cross-table rule type (household size vs person count is not checked; on the real data there are 0 mismatches). Referential and existential checks cannot be defined by users. Rules are edited in a file, not in the UI. **All three real releases have 0 violations.** |
| F4 | Automated flagging of inconsistent or unexpected patterns at individual or aggregate level | **PARTIALLY SATISFIED** | Individual: every record with an applicable value is ranked; CRITICAL band 5,700 (2024), 5,403 (2023-24), 13,238 (2025). FSU: 177 / 173 / 27 alerts. Area: 51 notable changes (2024). | Bands are positions in a ranking, not validated flags (§6). |
| F5 | User-friendly interface for interactive **and batch** validation | **PARTIALLY SATISFIED** | Interactive: the supervisor workspace (overview, ranked list with filters, case story, decision, next case, group alerts, area trends, technical reference, online record check). | Batch validation cannot be started from the UI (CLI or Docker only). |
| F6 | Dashboards on performance metrics | **PARTIALLY SATISFIED** | Overview (bands, review progress, reasons, State distribution), area trends, technical reference (coverage, evaluation tables). | No reviewer-productivity, model-performance-over-time or data-quality-over-time dashboards. |
| F7 | Data export / reporting | **PARTIALLY SATISFIED** | Streamed CSV of the full or filtered queue with review status (verified: all 415,549 rows; filtered 5,700). Machine-readable run reports (JSON/MD). | CSV only: no Excel/PDF, supervisor-wise, geographic or enumerator reports. |
| N1 | Open-source technologies | **FULLY SATISFIED** | Python, pandas, NumPy, SciPy, scikit-learn, DuckDB, PyArrow, FastAPI, uvicorn, SQLite, Docker. | — |
| N2 | Compliance with GoI data security and confidentiality guidelines | **NOT SATISFIED** (and not claimed) | Local-only binding, optional token authentication with roles, a hardened container, no external calls. | No TLS, no approved identity/MFA, no encryption at rest, audit not tamper-evident, no formal review (§13). |
| N3 | Value-added features | — | Explanations, FSU queue, area trends, influence, online check, Docker. | — |

### 2.4 Research document items (secondary; not brief requirements)

| Item | Status |
|---|---|
| Bayesian networks / hierarchical models | **NOT SATISFIED** (not implemented) |
| Autoencoder, DBSCAN, One-Class SVM, GMM, XGBoost | **NOT SATISFIED** (not implemented). Supervised models are impossible without labels. |
| Enumerator Quality Profile | **NOT ASSESSABLE** (no enumerator ID, interview duration not used) |
| Cross-survey validation | **NOT ASSESSABLE** |
| Human-in-the-loop with feedback improving models | **PARTIALLY SATISFIED.** The decision workflow and audit exist. Decisions are **not fed back** into any model, and no decisions have been recorded. |
| Model governance (version, parameters, traceability) | **PARTIALLY SATISFIED.** Every run stores method versions, parameters and input provenance, and every case carries its source run IDs. There is no approval workflow, registry or monitoring. |
| PSI, KS, JS, Wasserstein temporal drift on distributions | **NOT SATISFIED** as specified; robust-z screening of indicator changes is used instead. |

---

## 3. The core chain: where it succeeds and where it falls short

| Step | Verdict | Evidence |
|---|---|---|
| Survey data | **Strong** | Release-specific contracts; no imputation; blanks and zeros kept apart; 0 unmatched or ambiguous person→household links in all releases. |
| Validation (deterministic) | **Adequate, but finds nothing on the supplied data** | 11 documented rules, structural checks, 0 violations (released data). |
| Detection of unusual values | **Implemented, partly effective** | On injected non-rule errors, single statistical or historical comparisons recall 31–40 % at 1 % and 57–61 % at 5 %. Duplicate-person copies are almost never found (0 % at 1 %; 7–8 % at 5 %). Occupation miscodes are found weakly (3–9 % at 1 %). |
| Use of historical information | **Genuinely implemented, within each design period** | It reaches risk, the case page, filters and the overview ("Unusual compared with earlier periods": 2,464 of the 5,700 highest-priority records in 2024). It is the best single layer in the injection study. |
| Use of related-survey information | **Absent** (no data) | — |
| Statistical / probabilistic / ML analysis | **Present; ML adds no measured value** | Removing ML from the hybrid **raises** AP (2024: 0.504 → 0.525; 2025: 0.437 → 0.459). Removing contextual raises it more (0.566; 0.498). |
| Prioritisation | **The weakest link** | risk × influence, with provisional weights, a 0.995 override and fixed bands. It underperforms single layers on non-rule errors (§6). |
| Explanation | **Strong** | Every sentence is built from stored values. It never says "error"; FSU evidence is kept separate; model estimates are not called "typical". |
| Supervisor review / decision | **Implemented, unexercised** | Three decisions (issue, valid, needs follow-up), comments, next case. **0 decisions in the real audit stores.** |
| Audit trail | **Implemented; not tamper-evident** | Append-only by API convention, with evidence snapshots; the SQLite file itself is mutable. |

---

## 4. Statistical layer

**Method.** Within an assigned peer group (State/UT × sector × CWS status × occupation group or industry division, backing off to coarser levels, minimum 30), it computes the empirical mid-rank percentile, quantiles, median, MAD and robust deviation of each *applicable* value (salaried earnings, self-employment earnings, day-7 hours).

| Question | Finding |
|---|---|
| Appropriate method? | **Yes.** Robust, distribution-free placement is defensible for skewed earnings and discrete hours. |
| Reference population valid? | **Yes, with one limitation.** It is bounded by release, observation, design period, visit and (2025) month. Pre-2025 groups **pool all four quarters** (no seasonal boundary; peer-group code unchanged since 23 Sep), while 2025 groups are monthly. Seasonal agricultural hours and earnings are therefore judged against a year-round reference before 2025. |
| Survey design respected? | **Yes.** FSU and weights are excluded from comparability, and the design break is respected. |
| Weights? | Percentiles are **unweighted**: they describe the sample, not the population. That is defensible for validation but should be stated (it is, in DESIGN.md). |
| Missing / applicability? | **Correct since V1.1.** Questionnaire placeholders (0 for items not asked) are `NOT_ASSESSABLE`; genuine applicable zeros remain. Verified: no non-applicable person has a non-zero value in any release. |
| Revisit? | 2023-24 linked revisit changes are computed (exact documented person identity) but are **not in the first-visit review list**. |
| Interpretation defensible? | **Yes.** "Above the range covering 9 in 10 comparable records" is a correct description. By construction about 10 % of each group's applicable values fall outside the 5–95 % range, so "outside the range" is a description, not a flag rate. |

## 5. Contextual layer

**Method.** The surprisal of the person's 3-digit occupation code within its conditional frequency distribution, given State × sector × CWS status × industry division.

| Question | Finding |
|---|---|
| Meaningful comparison? | Partly. Rarity of an occupation within its industry and status context is a plausible miscoding signal. |
| Leakage? | None: occupation is not in its own conditioning set. |
| Size dependence | **Unresolved (audit M3).** A code held by one person in its group scores a median surprisal of 3.85 (reference < 100), 5.31 (100–499) or 6.70 (500+). The score is then globally rank-calibrated, so "unique in its group" ranks very differently depending on group size. |
| Over-claimed as error probability? | No. The UI says "uncommon occupation for similar people". |
| Value in evaluation | **Negative.** Contextual alone: AP 0.077 (2024). Removing it from the hybrid raises AP to 0.566, and occupation-miscode recall is only 8.7 % at 1 %. Yet 155 CRITICAL records (2024) are there through the override on a rare occupation **alone**. |

## 6. ML layer (each model separately)

| Model | Why appropriate | Target population | Zeros / not applicable | Features / leakage | Reproducible | Output meaning | Verdict |
|---|---|---|---|---|---|---|---|
| **Isolation Forest** | Generic multivariate rarity | All ready records in each release/visit/month boundary (415,549 in 2024) | Non-applicable earnings are missing, with indicators (V1.1) | Age band, log hours and earnings, one-hot sex, education, status, occupation group, industry division. No IDs, no weight. | Fixed seed, deterministic sampling; repeat run identical | A rank of isolation, mainly **rare category combinations** | **Weak.** 25 trees and a 10,000-row fit cap give a noisy ranking. It is the only ML score for non-workers, who never receive a priority anyway (no influence). |
| **LOF (distinct-point, peer-scoped)** | Local density within a comparable group | Day-7-hours peer groups; groups with ≤ 20 distinct vectors are not assessable (61,694 records) | Uses log earnings including non-applicable zeros, as distinct values | Age, hours, two earnings | Deterministic | Local density ratio. Fixed: max 17.6 (was 2.3 × 10⁸); 31 records above 10. | **Usable**; identical answers are no longer scored as anomalies. |
| **Gradient-boosted conditional model** | Expected salaried earnings given characteristics | Applicable positive salaried earners only (46,760) | Applicable zeros not modelled | Age, hours, sex, education, status, occupation, industry, State, sector. FSU-grouped two-fold cross-fitting; target never a predictor. | Deterministic early stopping | `|log observed − predicted|`; shown as "model estimate", never "typical" | **Sound after the V1.1 fix.** Estimate ÷ peer median 0.994 (was 0.474). It overlaps heavily with the statistical layer. |
| **Exact-signature similarity** | Copied responses | Blocked within FSU | — | Hash of ≥ 6 non-identifying responses | Deterministic | Informational only; not in risk (verified: `evidence_rank` null for all rows) | **Correctly bounded**, but finds almost no injected copies: `duplicate_person` recall 0 % at 1 %, 7.7 % at 5 % (2024). Near-duplicate matching is not implemented. |

Cross-cutting ML findings:
* The fused ML score is the **maximum** of three method ranks. A maximum of several ranks is biased towards high values, and this makes ML the most frequent override source: 891 of the 1,396 override-driven CRITICAL records in 2024.
* **No ML score is a probability of error**, and none is presented as one.
* ML is fitted **within** the scored round; it is not trained on historical data.

## 7. Pattern (FSU) layer

| Check | Comparison population | Direction correct? | Small FSUs | Finding |
|---|---|---|---|---|
| Distribution shift (G-test; Mann–Whitney among applicable values) | Leave-FSU-out, same release × visit × month × State × sector × stratum | Yes: direction comes from the medians, with "equal" stated when they are | Minimum 10; approximate p for 10–15 persons | 2024: 173 of 181 notable checks are **activity-status mix**. Neighbouring households really do differ, so this mostly reflects genuine heterogeneity, not data problems. |
| Reduced variance | Same | Yes ("varies less" only when true) | Centring on the FSU median makes small-FSU p-values slightly optimistic (documented) | 0 notable after correction (2024). |
| Age heaping (0/5) | Same | Yes (V1.1 fixed the earlier wrong-direction statements) | Binomial test | 2 notable (2024); 7 (2023-24). |
| Temporal drift (FSU) | — | — | — | **0 assessable**: each first-visit FSU is observed once. Correctly reported as not assessable; area drift is in `historical`. |
| Revisit transitions (2023-24) | Linked changes | Yes | Minimum 10 | 23 notable checks (2023-24). |

* **Group to individual:** correctly prevented. Pattern has no weight in record risk and cannot trigger the override. In the evaluation, members of fabricated FSUs had mean record risk 0.454 against 0.435 for all records.
* **2025 (current method, first run on 6 Oct 2026):** only **27 of 13,314** FSUs are notable: 24 age-concentration, 2 age-heaping and 1 age-distribution checks. Before the correction the evaluation flagged 54 % of clean 2025 FSUs. Whether the correction now under-flags in the small monthly cells is NOT ESTABLISHABLE FROM THE AVAILABLE EVIDENCE without re-evaluation.
* **Overdispersion correction:** a quasi-likelihood factor φ = median(χ²)/0.455, floored at 1, is applied per component and variable. It is a reasonable, standard idea, but it was introduced *after* the evaluation measured 15.8 % (2024) and 54 % (2025) of clean FSUs flagged. **The corrected method has not been re-evaluated**, so its recall on fabricated FSUs is NOT ESTABLISHABLE FROM THE AVAILABLE EVIDENCE.
* **Design periods:** respected (no pooling across January 2025 or across 2025 months).

## 8. Fusion

| Question | Finding |
|---|---|
| Calibration | Within-run empirical mid-rank per source. A value equal to its group median is rank 0 (V2 fix). Ranks remove magnitude, so a mild case at the 99th percentile looks like an extreme one. |
| Source weights (0.30 / 0.20 / 0.25 / 0.25) | **Engineering heuristics, not empirically validated.** The project's own ablation shows removing ML or contextual *improves* ranking. |
| Risk vs probability of error | Correctly never called a probability. |
| Influence | A per-variable selective-editing local score: `w·|y − m| / Σ w·|y|` over State × sector × period. It is unit-free (fixes mixed rupees/hours). It is **not** survey-estimator influence on LFPR/WPR/UR, and the UI says so ("has not been validated as the effect on official PLFS estimates"). "Weighted total of hours" is not a published PLFS estimate (low wording issue). |
| Incompatible units | Resolved by per-variable shares. |
| One source dominating | **Yes, via the override (≥ 0.995).** 2024 CRITICAL: 1,396 records override-driven (891 ML, 347 statistical, 158 contextual). |
| Double counting | risk and influence correlate at 0.60 (2024), because both grow with the deviation from the group median; earnings also feed statistical, ML and influence. Priority = risk × influence therefore rewards the same signal twice. |
| "99 % receive a priority" issue | **Resolved in form.** 166,722 of 415,549 records (40 %) get a priority, because records without an applicable value have no influence. CRITICAL = 5,700 (1.4 % of records), which by construction is about 2–3 % of prioritised records for two roughly uniform ranks. 5,700 CRITICAL cases per round is still a large queue. |
| Thresholds | The bands (0.8 / 0.5 / 0.2) are not scientifically justified, and the UI says so. |
| Does priority identify useful cases? | **Not on the evidence available** (§9). |
| Who can never be prioritised | 60 % of persons (non-workers, children, those not asked earnings or hours). Their ML or contextual anomalies never reach the queue, and age/status inconsistencies reach it only through rules. |

## 9. Evaluation science

**Software correctness.** 102 automated tests pass, natively and inside the Docker test image (98 before this delivery, plus 4 new). They show the code behaves as designed and protect previously found defects. **They say nothing about detection accuracy.**

**Scientific validity: the controlled injection study** (`evaluation/`, seed 20261003, six States, about 300 errors per type):

| | 2024 | 2025 (Jan–Jun) |
|---|---|---|
| Records / injected record errors | 107,081 / 2,373 | 150,649 / 2,378 |
| E6 full hybrid: AP (chance) | 0.504 (0.022) | 0.437 (0.016) |
| E6: precision / recall @1 % | 73.1 % / 33.0 % | 53.9 % / 34.1 % |
| E0 rules only: precision @1 % | 56.6 % | 40.2 % |
| **Non-rule errors (1,773 / 1,778), recall @1 %:** E6 hybrid | **10.3 %** | **11.9 %** |
| same, statistical alone | 33.4 % | 31.3 % |
| same, historical alone | 35.2 % | 39.8 % |
| Non-rule recall @5 %: E6 / statistical / historical | 48.9 % / 59.6 % / 60.0 % | 46.4 % / 56.6 % / 61.4 % |
| Removing ML from E6: AP | 0.504 → 0.525 | 0.437 → 0.459 |
| Removing contextual from E6: AP | 0.504 → 0.566 | 0.437 → 0.498 |
| Duplicate-person copies, recall @5 % | 7.7 % | 6.7 % |
| FSU fabrication (pre-correction method): recall / clean FSUs flagged | 100 % / 15.8 % | 56.7 % / 54.4 % |

Interpretation:
* **The headline precision is mainly a rules artefact.** The two rule-breaking injection types (600 records) receive priority 1 by design. 600 of the 783 true positives in the 2024 top 1 % are those records. Real releases contain **zero** such breaches, because CAPI hard checks prevent them.
* **Fusion currently hurts on the errors that matter.** For non-rule errors the combined priority is clearly worse at 1 % and somewhat worse at 5 % than the statistical or historical comparison alone.
* **Limits of the design:**
  * Errors are stylised, and the scale and keying errors are the kind a percentile test is built to find.
  * One seed and six States per release; no confidence intervals.
  * Unlabelled records may contain real errors, so precision is a lower bound.
  * The FSU results describe a method that has since been changed.
* **Not measured:**
  * Calibration (no probabilities are claimed, so this is acceptable).
  * Temporal stability across rounds.
  * FSU-level stability of rankings.
  * Reviewer workload or time per case.
  * Expert agreement.

**Operational usefulness: NOT ESTABLISHABLE FROM THE AVAILABLE EVIDENCE.** No supervisor has recorded a decision; the data are post-edit releases; no HSD-reviewed cases exist.

**Computational performance** (measured):
* Batch pipeline: 2024 took 979 s, with most stages reused and pattern taking 906 s. The original 2025 run took 5,713 s, of which historical took 3,869 s for 1.15 M persons. The 6 Oct 2025 rerun took 769 s (pattern 638 s, fusion 126 s; other stages reused) at about 1.4 GB.
* The ML layer peaked at about 2.1 GB.
* Docker workspace (named volume): overview 0.6–0.9 s, case page 0.9–1.2 s, case list 0.4–0.6 s; 2025 round (1.15 M records): overview 0.75 s, case page 1.1 s; full CSV export of 415,549 rows (109 MB) 7–10 s; idle memory about 110 MB.

## 10. Survey methodology

| Element | Respected? |
|---|---|
| State/UT, sector, stratum, FSU, household, person | Yes: keys preserved; FSU and stratum used as boundaries, never as ML predictors. State and sector are predictors only in the conditional earnings model (appropriate for an expected value). |
| District | Used in area screening and person context. |
| Visit / panel | First visit only in the review list; 2023-24 revisit linkage in the statistical layer; no cross-release linkage (correct: no common identity). |
| Design period, 2025 redesign | Hard boundary everywhere; January 2025 has no comparable earlier period. |
| Weights | Final weights per README (`MULT/100`, `/200` when NSS ≠ NSC; 2025 `MULT/100`) used for influence and area indicators. National indicators match published magnitudes. Comparisons themselves are unweighted (stated). |
| Release overlap | Calendar-2024 Q3/Q4 = 2023-24 Q3/Q4 (verified: 209,512 identical keys). Periods are de-duplicated, so no record is its own reference. |
| Monthly structure | 2025 peer groups and history are monthly; pre-2025 peer groups pool quarters (seasonality gap, §4). |
| First visit vs revisit | Kept apart. |
| Applicability | Correct and documented (Vol. I §3.6.17–3.6.19). |
| Comparisons across releases | Only in the historical layer, within the same design and with the same variable meaning. Valid in principle; nominal rupees are not deflated. |
| Area indicators | First-visit only (urban quarterly estimates also use revisits); SRS standard errors without design effects, so the screen is liberal. Not official estimates, and labelled as such. |

## 11. Historical / cross-round validation

* **Does historical information reach the validation decision?** **Yes.** In the 2024 run, 165,277 records have a historical score. It is one of four weighted sources, can trigger the override, is shown on the case page with the periods used, and is countable on the Overview.
* **Statistical evidence:** yes (the historical layer is itself statistical).
* **Contextual evidence:** no.
* **ML:** no; models are fitted within the round.
* **Temporal analysis:** yes, at area level (screening).
* **Cross-release linkage:** **not attempted, correctly.** First-visit FSUs are visited once, and no common person identity exists across releases.
* **Visible to the supervisor?** Yes: "Compared with earlier periods", with periods and reference size.
* **Precise answer:** historical data **is genuinely used** for record-level comparison and area screening within each design period. It is not used to train models, and 2025 cannot draw on pre-2025 history by design.

## 12. Supervisor workflow and UI

| Question | Answer |
|---|---|
| Can a non-technical supervisor understand the alert? | Yes. The headline is plain language; jargon sits behind "technical details". |
| What was observed, what was it compared against, why unusual? | Yes, per evidence block: observed value, comparison group and size, the range covering 9 in 10, earlier periods. |
| What should they verify? | Yes: a short checklist ("Confirm that ₹… was entered correctly", with a schedule reference). |
| Record a decision? Auditable? | Yes: three decisions plus a comment, an append-only event with an evidence snapshot, a reviewed list and CSV status. The actor is free text unless token authentication is on. |
| Overwhelming? | Mostly not (three levels of disclosure). The 5,700-case CRITICAL band per round is large for manual review. |
| Group vs individual evidence confused? | No. FSU evidence is a separate violet block and its own queue, and is shown on a case only when an FSU check is notable after multiple-testing correction. |
| Stronger claims than the evidence? | Mostly no. Two inaccurate statements on the Technical reference were corrected in this delivery (§17). Also corrected: the evaluation table, which made the hybrid look stronger than it is for non-rule errors; a derived non-rule view and an FSU-evaluation caveat now appear. |
| Usability tested with HSD supervisors? | **No.** NOT ESTABLISHABLE FROM THE AVAILABLE EVIDENCE. |

## 13. Security and Government-data readiness

| Area | Implemented | Not implemented |
|---|---|---|
| Confidentiality / local operation | Runs locally; no external calls; Docker port bound to 127.0.0.1; survey data never in the image | Encryption at rest (volume / Parquet) |
| Authentication | Optional bearer tokens (SHA-256 stored), roles supervisor / technical / admin; default **off** | TLS, SSO/MFA, GoI-approved identity, session expiry |
| Authorization | Only supervisor and admin may record decisions | Row-level (State-wise) access control |
| Audit | Decision and view events with actor, time and evidence snapshot | Tamper evidence (hash chain or WORM), access logging of reads/exports |
| Container | Non-root uid 10001, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, stored runs read-only, memory limit, health check | Image signing, vulnerability scanning in CI |
| Secrets | Users file mounted read-only (optional); proxy CA passed as a BuildKit secret, not stored | Secret manager |
| HTTP | CSP self-only, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, `no-store` on the API, no OpenAPI docs | Rate limiting |
| Exports | Streamed CSV | Export permissions, watermarking, export audit |

**GoI compliance is not claimed and is not met.** Local operation is a sensible prototype mitigation, not compliance.

## 14. Docker / deployment

**Design:** one application image and one app container (FastAPI serving UI and API; DuckDB over stored Parquet; SQLite audit per run), plus one-shot `seed`, optional `batch` and `tests` services. Separate frontend, worker or database containers would add infrastructure without benefit at the current scale.
**Data:**
* Never baked into the image.
* A named volume is filled from `MOSPI_DATA_DIR` (the repository or an exported bundle) by `scripts/export_serving_data.py`. It copies only the files the workspace reads (about 350 MB against 2.2 GB) and never overwrites existing files, so audit trails survive re-seeding.
* A Linux bind-mount override is provided.
* Bind mounts were measured 10–25× slower through Docker Desktop on Windows, which is why the volume is the default.

All results are recorded in [Validation results (Docker and tests)](#validation-results-docker-and-tests) below.

## 15. Scores

| # | Dimension | Score | Reason |
|---|---|---|---|
| 1 | Problem understanding | 8 | The documents state the brief's gap precisely and are honest about what the data cannot support. |
| 2 | Requirement coverage | 5 | Batch, export, interface and historical comparison exist. Real-time ingestion, related-survey validation, training and a user-definable referential rule facility do not. Several items are partial. |
| 3 | Survey methodology | 7 | Design boundaries, applicability, weights and release overlap are handled well. Pre-2025 seasonality pooling, first-visit-only area screening and SRS SEs remain. |
| 4 | Statistical correctness | 7 | Robust placement and historical comparison are correct and documented. Area screening is liberal. |
| 5 | ML correctness | 5 | Conditional model and LOF fixed. Isolation Forest weak; max-of-methods inflates ML; ML lowers fused performance in the project's own ablation; not trained on history. |
| 6 | Pattern analysis | 5 | Tested statistics with q-values and direction-safe wording. The queue is dominated by status-mix heterogeneity; the corrected method is unevaluated; the correction is post hoc. |
| 7 | Historical validation | 6 | Genuinely used and visible; strongest single layer in evaluation. Limited to 3 variables within the design period; no related data. |
| 8 | Evaluation methodology | 4 | An injection study with ablations exists (good). The headline is inflated by rule injections, it is single-seed with no CIs, the FSU results are stale, and there is no expert or real-error evidence. |
| 9 | Explainability | 8 | Faithful plain-language stories from stored values; careful limits. |
| 10 | Supervisor usability | 7 | Clear workflow and design. Large CRITICAL queue; never used by a supervisor; actor is free text by default. |
| 11 | Engineering quality | 7 | Provenance, immutability, determinism, tests. Found in this audit: a missing 2025 run, unpinned and incomplete dependencies, stale validation docs, broken document references. |
| 12 | Docker / deployment readiness | 8 | Reproducible, hardened, health-checked, tested end to end with restart persistence. Local-only by design. |
| 13 | Security / GoI readiness | 3 | Prototype controls only. |
| 14 | Research novelty / value | 6 | A useful combination of applicability-aware peer comparison, historical comparison, FSU testing and selective-editing influence with honest explanations. The fusion is not yet better than its parts. |
| 15 | Overall suitability for MoSPI | 5 | A sound foundation and decision-support prototype; not yet a validated validation platform; not deployable on GoI infrastructure as is. |

**Overall: 5.5 / 10.**

---

## 16. Findings by severity

### CRITICAL
* **C1. Fused priority is worse than its best single components on non-rule errors; the headline precision is a rules artefact.** Evidence in §9. *Consequence:* an evaluator can conclude that the ML/fusion layer does not add value and that "73.1 % precision" is overstated. *Fix in this delivery:* the Technical reference now shows non-rule recall by layer and says why the headline is high (presentation only; the algorithm is unchanged). *Must do next:* redesign or re-weight the priority (for example, statistical and historical as primary, ML and contextual as supporting without override), with a pre-registered re-evaluation using several seeds and confidence intervals.
* **C2. Real-world effectiveness cannot be established with the supplied data.** Evidence: released, post-edit data (0 rule violations, 0 household-size mismatches); no labels; 0 decisions. *Cannot be fixed with current data:* it needs eSigma pre-scrutiny submissions and HSD-reviewed outcomes (a pilot).

### HIGH
* **H1.** Real-time API ingestion is not implemented (F1). Only a store-nothing single-record check exists.
* **H2.** Related-survey validation is not assessable (B2), and enumerator analytics are not assessable (B3). Both are explicit in the brief.
* **H3.** The integrity "facility" is person-level, file-based and has no user-definable referential, existential or household rules (F3).
* **H4.** The FSU layer: the corrected method is unevaluated; about 95 % of pre-2025 alerts are activity-status mix, while 2025 has only 27 alerts out of 13,314 FSUs; the dispersion correction is post hoc (§7).
* **H5.** ML and contextual reduce fused performance in the project's own ablation; the override lets a single source (ML 891, contextual 158 in the 2024 CRITICAL band) set the top of the queue (§6, §8).
* **H6.** risk and influence share the deviation signal (r = 0.60); priority double-counts it. Weights, override and bands are unvalidated.
* **H7.** Security is prototype level (§13).
* **H8.** Not survey-general: PLFS mappings are in Python code (B8).
* **H9.** No learning from supervisor decisions, and no model approval or registry (research doc §22, §24).
* **H10** *(found in this audit; fixed in this delivery)*. **The current design (2025) was missing from the supervisor tool.** `pipeline/runs/2025_v2.json` recorded a completed pattern and fusion run, but `pattern/runs/2025_first_visit_v2` was empty and no 2025 fusion run existed. The directory was emptied at 17:33 on 3 October, right after the pattern overdispersion correction, and never rerun. The existing pipeline was rerun with unchanged code (§17, item 9).

### MEDIUM
* **M1.** Contextual surprisal is size-dependent (§5).
* **M2.** Pre-2025 peer groups pool quarters (seasonality).
* **M3.** Isolation Forest is under-powered (25 trees, 10,000 fit rows) and mainly ranks rare categories.
* **M4.** Area screening: first-visit only, SRS SEs without design effects, nominal rupees.
* **M5.** About 60 % of persons can never receive a priority (no applicable earnings or hours), whatever their other evidence.
* **M6.** 2023-24 revisit evidence is not in the review list.
* **M7.** Evaluation design: single seed, six States, no CIs; duplicate copies are almost undetected.
* **M8.** Stale documentation. `ml/VALIDATION_REPORT.md` describes V1 (30 iterations, all-person training). The README referenced a non-existent `EVALUATION_REPORT.md`, and the UI claimed audit "resolution notes appended", which did not exist. *The last two are fixed.*
* **M9.** `requirements.txt` was unpinned and omitted `scipy` and `pyyaml`, so a clean install broke the pattern layer and the online record check. *Fixed.*
* **M10.** Batch validation cannot be started from the UI; the 2025 historical stage takes about 64 minutes.
* **M11.** Export is CSV only; there are no supervisor-wise or geographic reports.

### LOW
* **L1.** "Weighted total of day-7 hours" is not a published PLFS estimate; the wording could say "weighted sum".
* **L2.** V1 Fusion runs remain selectable when the repository itself is served. They carry a warning banner, and the export bundle excludes them by default.
* **L3.** Read paths in `fusion/review.py` call `initialise()` (CREATE TABLE IF NOT EXISTS), so `fusion/runs` must be writable even for read-only use.
* **L4.** pandas FutureWarnings in `pattern/engine.py` and `statistical/revisit.py`.
* **L5.** Browser storage keys keep the `MoSPI.` prefix (kept deliberately so saved names and filters survive).
* **L6.** A true 390 px phone viewport could not be measured with the available headless browser (minimum about 500 px). At 500 px the layout and footer fit.

### STRENGTHS
* **Provenance discipline.** Every layer checks release, observation, design period and preparation run; runs are immutable; every case carries its source run IDs; ML reproducibility was verified by an identical re-run.
* **Questionnaire applicability** is handled correctly and cited, so placeholder zeros never become evidence.
* **Final weights and release overlap** are handled correctly (validated against the READMEs and published magnitudes; de-duplicated quarters).
* **The January-2025 design break** is respected everywhere.
* **Historical comparison** genuinely reaches the decision and the supervisor. It is the best single detector in the controlled study.
* **Group evidence is never transferred to individuals** (verified in data and evaluation).
* **Explanations are faithful** and never overclaim ("unusual ≠ incorrect", "model estimate", FSU ≠ enumerator).
* **A human-in-the-loop audit** with an evidence snapshot per decision.
* **Honest status labelling** (Validated / Evaluated / Provisional / Not assessable) in the UI and documents.
* **A clean, hardened, reproducible Docker deployment** with measured performance.

---

## 17. Changes made in this delivery (audit trail)

No evidence algorithm, model, weight or threshold was changed.

| # | Change | Why | Files |
|---|---|---|---|
| 1 | MoSPI naming in the UI shell, page title, browser title, footer wordmark, API title, export file name, CLI help and documentation headings. `MoSPI_*` columns, method-version strings, logger names, storage keys and dated historical documents kept. | Part 1; those identifiers are stored inside runs or are provenance. | `fusion/ui/index.html`, `fusion/ui/app.js`, `fusion/ui/styles.css`, `fusion/api.py`, `fusion/serve.py`, `fusion/cli.py`, `pipeline/run.py`, `fusion/README.md`, `docs/ESIGMA_INTEGRATION_ROADMAP.md`, `README.md` |
| 2 | "Powered by INNODATATICS": a one-line attribution strip at the foot of every page (the app is a single-page shell, so the footer is on every view); stacks on narrow screens. | Part 2 | `fusion/ui/index.html`, `fusion/ui/styles.css` |
| 3 | `/healthz` readiness endpoint: no authentication, no paths or records. | Docker health check | `fusion/api.py` |
| 4 | Server settings via `MOSPI_*` environment variables; an explicit `MOSPI_CONTAINER=1` opt-in to bind the container interface without authentication (refused otherwise). | Docker; keeps the local-only safeguard | `fusion/serve.py` |
| 5 | Pinned `requirements.txt` (adds the missing `scipy`, `PyYAML`); new `requirements-dev.txt`. | M9: reproducibility | `requirements*.txt` |
| 6 | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `docker-compose.bind.yml`, `deploy/no-extra-ca.pem`, `scripts/export_serving_data.py`, `docs/DOCKER.md`. | Part 3 | new |
| 7 | Technical reference: (a) the false "resolution notes appended" claim replaced with correct document pointers; (b) a caveat that the FSU evaluation predates the overdispersion correction; (c) derived non-rule recall by layer, computed only from stored per-type recall, with a data-driven sentence. | Honesty of displayed claims (C1, M8) | `fusion/ui/app.js` |
| 8 | 4 new tests (health with and without runs, export name, bind guard). | Regression protection | `fusion/tests/test_explain.py` |
| 9 | **2025 pattern and fusion runs produced** (result: 1,148,634 records, 429,227 prioritised, CRITICAL 13,238, 27 FSU alerts, 0 rule violations) with the existing, unchanged pipeline (`python -m pipeline.run --release 2025 --suffix v2`), reusing the stored statistical, ML, historical and integrity runs. The empty leftover directory `pattern/runs/2025_first_visit_v2` (no files) was removed first, as the pipeline requires; the previous pipeline record was preserved in the session log. | H10: the current PLFS design was absent from the tool | `pattern/runs/2025_first_visit_v2/`, `fusion/runs/2025_first_visit_v2/`, `pipeline/runs/2025_v2.json` |
| 10 | This report; README status table rewritten (fixes the reference to a non-existent `EVALUATION_REPORT.md`). | Part 4 | `docs/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md`, `README.md` |

## 18. What to do next

**Must fix before an operational pilot**
1. Re-design and re-evaluate the priority (C1, H5, H6). Use several seeds, all States, confidence intervals, and report non-rule metrics as the headline.
2. Re-run the evaluation for the corrected FSU method (H4).
3. Agree a pilot with HSD on eSigma pre-scrutiny data, with supervisors recording decisions (C2). This is the only route to real effectiveness evidence.
4. Security: TLS, approved identity, tamper-evident audit, encryption at rest, export controls (H7).

**Should fix if feasible**
* Ingestion API (H1).
* Household-level and referential rule types, editable from the UI (H3).
* Seasonal peer boundaries pre-2025 (M2).
* Size-adjusted contextual score or remove contextual from the override (M1).
* Revisit evidence in the list (M6).
* Excel/PDF reports (M11).
* Update `ml/VALIDATION_REPORT.md` (M8).
* A training pack (O4).

**Cannot honestly be fixed with current data**
* Related-survey validation (B2).
* Enumerator analytics (B3).
* Real-error accuracy (C2).
* Cross-release person linkage (no common identity).

**Keep as documented future work**
* Bayesian / probabilistic joint-response models.
* A metadata-driven multi-survey configuration (H8).
* eSigma integration (B9).

---

## Validation results (Docker and tests)

*Recorded on 6 October 2026, Windows 11, Docker Desktop (engine 29.2.1, Compose 5.0.2, 8 GB / 12 CPUs to the VM).*

| # | Check | Command / method | Result |
|---|---|---|---|
| T1 | Existing tests (baseline, before any change) | `python -m pytest -q` | **98 passed** |
| T2 | Tests after all changes, native | `python -m pytest -q` | **102 passed** (4 new) |
| T3 | Tests inside Docker | `docker compose --profile test run --rm tests` | **102 passed** in 23.6 s |
| D1 | Image build | `docker compose build` (with `MOSPI_EXTRA_CA_FILE`, because Avast re-signs HTTPS on this machine; without it pip fails with `CERTIFICATE_VERIFY_FAILED`) | Built: 239 MB content / 1.02 GB unpacked; contains no survey data, audit file or proxy CA (inspected) |
| D2 | Data volume | `docker compose --profile seed run --rm seed` | 3 Fusion runs plus referenced source runs, `missing_source_runs: []`; volume 805 MB |
| D3 | Startup and health | `docker compose up -d`; `GET /healthz` | Healthy in about 6 s; `{"status":"ok","runs":3,"default_run":"2025_first_visit_v2", all source runs found, audit store writable}` |
| D4 | API, frontend, branding | Black-box script (37 checks) against `http://127.0.0.1:8765` | Index, JS, CSS and fonts served (served JS content checked, not just URLs); title "MoSPI · Survey Data Validation"; no "MoSPI" in the shell; "Powered by INNODATATICS" present; CSP and frame headers set. **37/37 passed.** |
| D5 | Real data | `/api/overview` | 2024: 415,549 records / 166,722 prioritised / 5,700 CRITICAL, equal to the stored fusion report; 2023-24: 418,159; 2025: 1,148,634 / 429,227 |
| D6 | Case list, filters, navigation | `/api/cases`, `/api/queue/position` | Priority order; band + State filter (176), strong-historical filter (8,261), position lookup correct |
| D7 | Case page | `/api/cases/{id}` | Story with headline, reasons and checks; no error or probability claims |
| D8 | Review workflow and audit | `POST /api/cases/{id}/events` | View and decision appended with evidence snapshot; invalid decision → 422; status, history, reviewed list and unreviewed filter consistent |
| D9 | Export | `/api/export/queue` | Filtered 5,700 rows; full 415,549 rows (109 MB), streamed; carries review status; file `mospi-review-queue.csv` |
| D10 | Group alerts | `/api/groups`, `/api/groups/{fsu}` | 177 (2024), 27 (2025) with plain-language patterns |
| D11 | Area trends | `/api/aggregates` | 51 notable changes (2024) |
| D12 | Technical reference | `/api/summary`, `/api/evaluation`, `/api/integrity`, `/api/validate/record`, page screenshot | Evaluation 2024 + 2025; integrity 0 violations; online rule check flags R05; comparison-group check assessed; non-rule recall table renders with values equal to an independent recomputation |
| D13 | Restart persistence | `docker compose restart`; `down` + `up`; re-seed; image rebuild + `up` | Decision present after each; re-seed copied only the 87 KB evaluation results |
| D14 | Hardening | `exec` probes; `docker inspect`; LAN-IP request | Stored runs and `/app` read-only; `fusion/runs` writable; uid 10001; `cap_drop ALL`; `no-new-privileges`; 3 GB limit; port 127.0.0.1 only (LAN request refused) |
| D15 | Performance (volume vs Windows bind mount) | Timed endpoints | Case page 0.9–1.2 s on the volume against 20–30 s on a bind mount (hence the volume default) |
| D16 | Batch service | `docker compose --profile batch run --rm batch` | Pipeline CLI and all layer imports load. A full batch run was executed natively, not in Docker (§17, item 9). |
| D17 | Repository audit untouched | `sha256sum -c` | `fusion/runs/2024_first_visit_v2/review_audit.sqlite: OK`; all test decisions were written to the volume copy |
| U1 | Responsive UI | Headless Edge at 1440 px and 500 px | Footer and attribution correct at both. A 390 px capture was cropped by the headless browser's minimum width (about 500 px), so a true phone viewport is not verified (L6). |
| U2 | Pipeline: 2025 rerun | `python -m pipeline.run --release 2025 --suffix v2` | Exit 0 in 769 s; outputs above |

A problem found and fixed during testing: the first container test passed asset checks while serving a stale `app.js`, because the version query string is not used by the server. The check now verifies served content, and the image was rebuilt.

An observation during testing: a serving bundle exported to the Windows `%TEMP%` scratch area lost its `preprocessing/` and `contextual/` folders a few minutes after export. The cause is not established; antivirus or temp cleanup are possible. The repository was verified intact. The documented procedure seeds from a chosen directory, and the seed step fails loudly (`missing_source_runs`) on incomplete data.
