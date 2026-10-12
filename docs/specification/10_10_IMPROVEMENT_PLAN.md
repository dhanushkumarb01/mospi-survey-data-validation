# 10/10 improvement plan: MoSPI Intelligent Survey Data Validation Platform (PLFS)

**Status:** plan written 8 October 2026; **implementation pass completed 9 October 2026 in the existing V2 code (no parallel system)**; **completion sprint later on 9 October 2026** (calibration corrections, batch validation from the workspace, first development runs of the evaluation protocol), reported in [`V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md`](V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md). The implementation status of every work item is in the section below. The plan text after it is unchanged, except this header.
**Date:** 8 October 2026.
**Primary authority:** *A brief note from HSD, NSO, MoSPI*, "the brief".
**Secondary:** *Research & Technical Documentation v1.0*, "the research document"; it elaborates the brief but does not add requirements.
**Baseline:** [`FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md`](FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md) (5.5/10), "the 5.5 evaluation".

**How this plan was produced.** The code was read stage by stage. Every number below comes from one of three sources:
* the stored runs, queried read-only;
* the test suite (102 passed on 8 Oct 2026);
* new read-only diagnostics on the stored evaluation evidence (§5.10 says how to reproduce them).

Where something cannot be checked with the available data, it is marked **NOT ESTABLISHABLE** and the missing evidence is named.


## Implementation status (9 October 2026)

### Completion sprint (9 October 2026, later) — what changed
Details, evidence and commands: [`V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md`](V2_COMPLETION_AND_IMPLEMENTATION_REPORT.md).
* **Calibration (W2.3, W5.2):** Tarone count of discrete tests in the value lane (fusion v2.2); State-conditional conformal calibration of the expected-value models (ML v2.1); FSU combination v2 (the Cauchy p = 1 veto removed; short-interview, near-duplicate and response-code checks context-only because their p-values fire 2–16x nominal on released data). New runs `v2_2` for 2024 and 2025 (only ML and fusion re-run; V2.1 runs untouched). Observed/nominal value alerts 0.51 → 0.82 (2024, met) and 0.52 → 0.73 (2025, **not met**); highest/median State "Check now" 3.27 → 3.51 and 4.73 → 3.06 (**not met**, Nagaland drift in 2024, Lakshadweep calibration in 2025); FSU alerts 0.43% → 0.97% and 2.9% → 0.11% (met, but injected paradata/copying FSUs are then not found).
* **Batch from the UI (W8.7): done.** "Batch validation" page and `/api/batch*`: supported prepared inputs, start (admin), status, errors, interrupted detection, open the result; upload not offered (server-side preparation). 6 tests with real pipeline processes.
* **Evaluation (§12): development runs only.** Seed 1, fold A, 2024 and 2025, verified. D beats A0 by +13.4 / +14.4 points of R@1% (CIs above 0); **the expected-value model alone beats D by 2.9 / 6.4 points** (criterion 1 fails on development data). Coding lane 82% / 69% at 5% (criterion 4 met); rules 100%. Confirmation seeds 6–20 on fold B **not run**.
* **2023-24:** re-run for the first time with the current method (`v2_2`, every stage, 1,400 s), started through the new batch API; all gates passed; observed/nominal 0.825, State ratio 3.44 (not met), FSU alerts 1.0%. The V2.0 run is kept.
* Tests: 140 default passed, 15 real-data passed.

Words used: **Done** (implemented and covered by automated tests), **Done, not evaluated** (implemented and tested for correct behaviour; its error-detection value has not been measured), **Partial**, **Not done**, **Later stage** (PostgreSQL / eSigma / deployment, deliberately out of this pass), **Gated** (needs HSD/eSigma input G1–G7).

**What was run (implementation pass; superseded where the sprint block above says so).** 140 automated tests: 129 run by default, 11 real-data smoke tests opt-in (`pytest -m realdata --realdata`). Full V2 batches on the stored 2024 and 2025 releases with suffix `v2_1` (all stages, all quality gates passed; the 2023-24 release was not re-run). 2025: 5,444 "Check now" cases of 1,148,634 records (budget 11,487); observed/nominal value alerts 0.52; highest/median State rate 4.7 (target ≤ 3, not met); 44 of 52 model fits trained on earlier months (January uses the labelled in-round fallback); 394 FSU alerts among 13,392 assessable FSUs (2.9%, target ≤ 2%, not met) with 9,202 FSUs not assessable in monthly cells; historical stage 9 minutes (64 minutes before). Real-data smoke tests (12) passed, including the case page on every stored legacy fusion run. **The evaluation campaign of §12 has not been run.** No number below is a detection-accuracy result.

### Phase 0
| Item | Status | Where |
|---|---|---|
| W0.1 schema read boundary | Done: legacy `iospi_*` and current `MoSPI_*` read through `survey_rules/schema.py`; stored runs never rewritten; `schema_version` in new preparation metadata; case-page defect (N1) fixed | `survey_rules/schema.py`, all readers, `fusion/explain.py` |
| W0.2 fail loudly | Done (historical, fusion, integrity, every reader) | tests in `historical/tests` |
| W0.3 run QA gates | Done; fault-injection tests | `pipeline/qa.py` |
| W0.4 reproducible evaluation artefacts | Done in code (`--verify`, commit/hashes/seed recorded); not exercised on a real campaign | `evaluation/run.py` |
| W0.5 image provenance | Done: `MOSPI_CODE_VERSION` build arg, OCI label, `/healthz`, `/api/version`. Not rebuilt or container-tested in this pass | `Dockerfile`, `docker-compose.yml` |
| W0.6 documentation truth check | Not done (docs updated by hand) | — |

### Phase 1 (instrument built; campaign not run)
**Sprint: two development runs (seed 1, fold A) made and verified; confirmation not run.** W1.1 catalogue v2 (×12, ×100, plausible-but-wrong, casual wage, copied household, short interviews, one-day completion) — done, labelling test. W1.2 seeds and State folds — done. W1.3 CAPI-pass metric — done, fixture test. W1.4 paired bootstrap — done (Kendall τ and PR curves not yet). W1.5 `evaluation/PROTOCOL.md` — committed before any confirmation run. W1.6 real-data burden — in every fusion report. W1.7 baseline A0 — rebuilt from stage outputs in `evaluation/run.py`, **not run**. W1.8 diagnostics script — not done.

### Phase 2 — evidence and priority redesign (V2.0 fusion replaced in place)
| Item | Status |
|---|---|
| W2.1 lanes, no influence product, no override | Done, not evaluated (`fusion/lanes.py`, `fusion/queue.py`, `fusion/engine.py`); old method kept only as baseline A0 (`fusion/legacy.py`) |
| W2.2 per-variable combination | Done, not evaluated: mean of current-peer and earlier-period tail probabilities, OR (Šidák) with the expected-value model, Šidák across variables |
| W2.3 calibrated tail probabilities | Partial: finite-sample (conformal) probabilities per reference; Tarone count of discrete tests and State-conditional model calibration (9 Oct sprint). Observed/nominal 0.51 → **0.82** (2024, target met) and 0.52 → **0.73** (2025, not met) |
| W2.4 IF/LOF out of priority | Done (`decision_path = RESEARCH_ONLY`; fusion does not read them) |
| W2.5 coding lane | Done, not evaluated: conformal frequency tail probability (size-invariance test). A first leave-one-out Dirichlet version flagged 1.6% of 2024 records below 0.001 and was replaced before use. 2024: 5 coding cases in "Check now" |
| W2.6 override removed | Done |
| W2.7 impact ÷ design SE, ordering only | Done, not evaluated (`fusion/impact.py`) |
| W2.8 tiers, budget, FSU grouping and cap | Done; budget 1% is a provisional default (HSD capacity unknown). V2.2: 2024 3,079 "Check now" (budget 4,156), State ratio 3.51; 2025 7,634 (budget 11,487), ratio 3.06 (target ≤ 3 not met; V2.0 was ~18) |
| W2.9 leave-one-out; quarter boundary | Done (statistical v2.0; peer spec v1.1) |
| W2.10 revisit lane | Not done (2023-24 linked changes still computed but not in the queue) |

### Phase 3 — historical
W3.1 hashed reference snapshot written and registered per run — done (scoring still builds from the pool in the same run; snapshot-only scoring for online use not done). W3.2 same-season comparison — done for pre-2025; 2025 gated (G7). W3.3 deflation — not done (needs HSD-approved deflator). W3.4 casual daily wage — done across peer, statistical, historical, ML, integrity; activity hours, MPCE as a value variable, household size — not done. W3.5 models trained on earlier periods, four targets, conformal ranges, model registry — done; 2024: 16 of 16 fits trained on earlier periods. W3.6 design-based SEs (median design effect 1.1–3.0 in 2024), same-season change, distribution drift, known-events calendar (empty) — done, not evaluated. W3.7 historical presentation — done. W3.8 related sources — gated (G2).

### Phase 4 — integrity
13 rule types (W4.1) and household level (W4.2) — done. W4.3 district code list — done for 2025; the pre-2025 list predates 54 codes used in 2024, so the rule is limited to 2025 until HSD supplies the current list. W4.4 test cases on load + dry run per batch — done; every approved hard rule has 0 violations on all three stored releases. W4.5 approval workflow — metadata and drafts only; no admin UI. W4.6 transcribed rules with citations (Block 6 item 4, Block 3 item 5.6 and 7.5, Block 6 col. 9, Block 4 col. 15, existential head and size rules) — done. W4.7 soft rules — two drafts, inactive.

### Phase 5 — FSU / pattern
W5.1 baseline evaluation — development runs only (sprint): fabrication 100% / 50%, copied household 3% / 0%, short interviews 0% / 0%, one day 7% / 0%, clean-FSU alert rate 0.97% / 0.11%. W5.2 FSU combination + BH across FSUs (v2: Bonferroni over calibrated checks; three fieldwork checks context-only), W5.3 local φ, W5.4 standardised status mix, W5.5 paradata, W5.6 near-duplicates — done, not evaluated (2024: 55 of 12,748 FSUs alert, 49 with a fieldwork signal). W5.7 exact small-FSU tests — not done. W5.8 enumerator lane — gated (G3; the paper schedule has an enumerator code but the released files do not).

### Phase 6 — categorical consistency model
Not done (research gate).

### Phase 7 — ingestion, storage
Later stage: PostgreSQL schema, ingestion API, scheduler, revision handling, mock eSigma adapter. W7.7 tamper evidence was implemented within SQLite instead: hash chain, append-only triggers, verifier, legacy rows sealed without being modified.

### Phase 8 — supervisor workflow
W8.1 worklist grouped by FSU and household — done (`/api/worklist`; scope assignment needs identities — later stage). W8.2 decision taxonomy, reason codes, verification source, corrected value — done. W8.3 time on case — done (server-side from the case-open time). W8.4 feedback report with proposals never applied — done (`/api/feedback`). W8.5 dashboard — partial (workload, decisions, burden, State rates; no time series). W8.6 Excel/PDF reports — not done (CSV export only). W8.7 batch from the UI — done (sprint; upload not offered). The UI was rebuilt in place as a plain monitoring dashboard.

### Phase 9 — security
Export role-gated and logged; unauthenticated actors stored as unverified; bounded inputs; read-only audit reads; hash-chained audit. Authentication on by default, OIDC, TLS, backups, scanning — later stage / needs MoSPI infrastructure (G4).

### Phase 10 — generalisation
Partial: survey-specific mappings consolidated in the survey layer (`survey_rules/plfs*.py`, `peer_groups/config.py`, rule YAML); lanes, queue, impact, variance, schema and rule engine are concept-based. No survey pack or second-survey onboarding.

### Phase 11 — training and pilot
Not done; pilot gated (G1, G6).

---

## 1. Executive verdict

**The 5.5 evaluation was right about direction and wrong about two things.** It understated the current state's problems, and it misattributed part of the fusion failure.

1. **The committed code cannot read its own stored data (new, CRITICAL).**
   * The `IoSPI → MoSPI` rename changed every internal column reference from `iospi_*` to `MoSPI_*`. Every stored prepared run still uses `iospi_*`.
   * The running container returns HTTP 200 only because its image was built on 6 Oct from the older code: 22 files inside it still contain `iospi_`, against 0 in the repository.
   * On the committed code:
     * the case page fails (`BinderException: "MoSPI_record_key" not found` in `fusion/explain.py:274`);
     * `fusion.engine` refuses to run ("Prepared persons file lacks the documented source identity fields");
     * the evaluation cannot run;
     * **the historical stage silently "succeeds"**: all 415,549 records come out with blank State, sector and period and `ready = False`, because `historical/engine.py: load_release` fills missing columns with `""`.
   * The 102 tests pass only because their fixtures were renamed too.
   * The next `docker compose build` would ship a broken product.
2. **The headline fusion failure is real, but the 10.3% figure is an artefact of the metric.**
   * In E6 the 600 rule-breaking injections take 600 of the 1,071 top-1% slots. That caps non-rule recall at 26.6% before any evidence is considered.
   * Measured fairly, on the records CAPI would pass (rule breakers removed), the current fusion finds **21.7% (2024) and 17.8% (2025)** of non-rule errors in the top 1%. The statistical layer alone finds 33.4% and 31.3%; the historical layer alone 35.1% and 39.5%.
   * So fusion does lose evidence, by about half, not by two-thirds.
3. **Why fusion loses evidence (root cause, measured):**
   * **Averaging ranks dilutes evidence.** Detectors look at different variables, so a value error is visible to one or two layers and invisible to the rest. Injected value errors sit at mean rank 0.55 in the contextual score, which is pure noise for them, so averaging pulls them down.
   * **Isolation Forest adds noise.** On its own it finds 1.5% and 4.0% of errors in the top 1%, where chance is 1%. Yet it is the arg-max of 65% of the "ML" top-1%, through the max-of-methods rule, and ML drives 891 of the 1,396 override-driven CRITICAL records.
   * **Contextual surprisal depends on group size.** Clean records in its top 1% come from reference groups with a median size of 1,353, against 324 overall.
4. **The current influence measure distorts the queue geographically.**
   * Influence is a share of a State × sector total, so small domains produce large shares.
   * Share of prioritised records that are CRITICAL (2024): Lakshadweep **20.4%**, A&N Islands **18.6%**, Chandigarh **15.8%**, against Uttar Pradesh **1.15%** and Maharashtra **1.33%**.
   * A supervisor queue built on this over-reviews the smallest UTs and under-reviews the largest States.
5. **A simpler, evidence-led design does much better on the same stored evidence.** Read-only experiment, CAPI-pass population, recall in the top 1% with bootstrap 95% CIs:

   | Design | 2024 | 2025 |
   |---|---|---|
   | Current fusion | 21.7% [19.7, 23.4] | 17.8% [16.1, 19.5] |
   | Statistical + historical, mean of ranks | **39.7% [37.5, 41.9]** | **38.0% [35.8, 40.1]** |
   | max(statistical + historical, conditional earnings model) | **42.0%** (precision 70.0%) | **41.6%** (precision 49.3%) |
   | Adding ML by *averaging* (weight 0.2) | 29.6% | 27.8% |

   * The conditional model, a cross-fitted expected-earnings model, **does** add value when combined by maximum. Averaging is what destroyed it.
   * Isolation Forest and LOF do not add value.
   * Caveat: these designs were compared on the single stored injection seed. **They are hypotheses to confirm under the pre-registered protocol in §12, not results.**
6. **What cannot be made 10/10 without HSD/eSigma**, whatever we build:
   * real-world accuracy (needs pre-scrutiny eSigma data and supervisor decisions);
   * related-survey validation (needs approved related datasets);
   * enumerator analytics (needs an investigator identifier);
   * GoI security compliance (needs MoSPI's hosting, identity provider and security review);
   * HSD usability evidence and training delivery.

   §24 defines what "10/10" means for work we control (an **internal ceiling**). It also names the external gates (G1–G7) a strict evaluator would rightly require before awarding 10.

**Bottom line.**
* The platform's strongest assets are its survey-design handling, its historical comparison, its explanations and its provenance discipline. They are worth keeping.
* Its fusion/priority layer is the weakest part and should be **replaced, not tuned**.
* Isolation Forest and LOF should leave the priority path.
* Contextual evidence should become a separate, small "coding check" list.
* Influence should stop multiplying risk.
* Two thirds of the brief's integrity, ingestion and aggregate requirements need new work. Much of it can use data the platform already has but ignores: interview duration, survey date, the 7-day time disposition, household consumption and response codes.

---

## 2. What the MoSPI problem actually is

### 2.1 The operational situation, from the brief's own words

* Enumerators enter data in **CAPI**, and it is "centrally updated in the eSigma platform".
* CAPI already runs **hard and soft checks** that "ensure basic syntactic and logical consistency".
* **Field Supervisors and Data Supervisors** are "responsible for scrutinizing, inspecting and flagging inconsistencies".
* The gap: "there is no mechanism at present to the supervisors to use the **past data or related survey data** for checking anomalies and inconsistencies".
* Rule checks "are insufficient to detect complex, contextual, or distributional anomalies such as **enumerator bias, temporal drifts, unusual response patterns, or inconsistencies relative to historical trends or related surveys**".
* Aggregate analysis for the **monthly bulletin** is done separately, "by extracting the data from eSigma platform using custom developed queries".
* Requested: "a software tool for both **online and offline** validation … using probabilistic and machine learning based models on **historical datasets** to aid the HSD officials". It starts with PLFS, must be general purpose, and may later be integrated in eSigma.

### 2.2 What the platform must accomplish

| # | Capability | Brief anchor |
|---|---|---|
| P1 | Accept survey data online (API) and in periodic batches, and check its structure | Feature 1 |
| P2 | Run user-definable integrity checks (referential, existential, …) | Feature 3 |
| P3 | Find records that are **technically valid but improbable**, compared with current peers, the same cell in **past rounds** and, when supplied, **related surveys** | Background; Objective 2 |
| P4 | Find **group-level** patterns (cluster/FSU, and enumerator when an ID exists) and **aggregate/temporal** shifts | Background; Objective 2; Feature 4 |
| P5 | Build statistical, probabilistic and ML models **from historical data** and apply them to new data | Feature 2; Objective 2 |
| P6 | Give supervisors a usable interface for interactive and batch validation, with prioritised, explained flags, decisions and an audit trail | Features 4, 5 |
| P7 | Dashboards on performance metrics; export and reporting | Features 6, 7 |
| P8 | Evaluate on PLFS 2024 onwards with defined measurement criteria | Objective 3 |
| P9 | Open source, low cost, scalable, cloud-ready, compliant with GoI security | Notes 1, 2 |
| P10 | Training for HSD, and an eSigma integration roadmap | Objectives 4, 5 |

### 2.3 The central definition of success

> **For each batch or submission of CAPI-valid survey data, the platform gives every Field/Data Supervisor a short, workload-bounded, plain-language list of records, households, FSUs and areas.**
>
> **The list contains values that are improbable compared with comparable current records, the same cell in earlier rounds and (when supplied) related surveys, together with exactly what to verify.**
>
> **Verifying that list catches materially more real errors than CAPI rules and unaided scrutiny would, at a known and controlled false-alert rate. Every decision is recorded and feeds the next round's calibration.**

Measurable form:
* **Incremental value:** recall of CAPI-passing errors within a fixed review budget (for example 1% of records, or N cases per supervisor-day), compared with E0 (rules only) and with the best single detector.
* **Burden:** expected false alerts per 1,000 clean records, and per FSU, on real released data.
* **Real effect (pilot):** confirmed-issue rate among flagged cases (true precision), plus the miss rate estimated from a random audit sample of unflagged records.

**The difference from CAPI.** CAPI asks "is this value allowed?". The platform asks:
* "is this value believable for *this* person, here, now, given what similar people reported this round and in previous rounds?"
* "does this FSU, or this area, look like it did before?"

Everything that does not serve this definition is secondary and should not shape the priority queue.

---

## 3. Current architecture assessment (code, not documentation)

Traced execution path: `pipeline/run.py` →
* `preprocessing` → `peer_groups` → `statistical` → `contextual` → `ml` → `pattern` → `historical` → `integrity` → `fusion.engine`,

then the serving path:
* `fusion.api` → `fusion.explain` → `fusion/ui` → `fusion.review` (SQLite audit).

| Stage | What actually runs | Consumes → produces | Key assumptions | Evidence for assumptions | Used downstream? | Scientifically appropriate? | Evaluated? | Incremental value | Brief requirement |
|---|---|---|---|---|---|---|---|---|---|
| **Preprocessing** (`preprocessing/pipeline.py`, `config.py`) | Release contracts, key building, code-set checks, duplicate keys, person→household linkage | Raw CSV → `prepared_persons/households.parquet`, issue log | Layouts as documented | 0 unmatched or ambiguous links in all releases (5.5 evaluation) | Yes, by all layers | Yes | Structurally | Foundation | P1 (batch, schema) |
| **Survey-design rules** (`survey_rules/plfs.py`) | Applicability by CWS (Vol. I §3.6.17–19), final weights (README formulas), period index | Codes → applicability, weights | Documented rules | Cited; no non-applicable person has a non-zero value | Yes (stat, hist, ML, fusion) | Yes | By tests | High: it prevents placeholder zeros becoming "evidence" | P3, P8 |
| **Peer groups** (`peer_groups/`) | State × sector × CWS × occupation group or industry division, with backoff, minimum 30; 2025 by month; **pre-2025 pools all quarters** | Prepared → assignments, references | Comparable people earn and work alike | Reasonable; pooling ignores seasonality | Yes (stat, contextual, LOF) | Mostly; seasonal gap pre-2025 | Indirectly | Needed by statistical | P3 |
| **Statistical** (`statistical/engine.py`, `statistics.py`) | Mid-rank percentile, quantiles, MAD for 3 targets (salaried earnings, self-employment earnings, day-7 hours) | → `statistical_evidence.parquet` | Reference includes **the observation itself** and **all current-round errors** | Not justified; leave-one-out not used | Yes: fusion uses `|percentile − 0.5| × 2` | Yes as a description; contaminated as a test | Yes: alone 33.4% / 31.3% (CAPI-pass, top 1%) | **Strong** | P3 |
| **Contextual** (`contextual/`) | Surprisal of the 3-digit occupation within State × sector × CWS × industry | → `contextual_evidence.parquet` | Rarity signals a miscode | Partly. Score grows with reference size (clean top-1% median ref 1,353 vs 324) | Yes, weight 0.20, and can trigger the override | Size-biased; not a calibrated tail probability | Yes: alone 8.1% / 7.3%; occupation miscodes 39% / 27% | **Harmful in the mean; useful only for coding errors** | P3 (contextual) |
| **ML: Isolation Forest** (`ml/isolation_forest.py`) | 25 trees, 10k fit rows, all persons | → ranks | Multivariate rarity signals error | **None**: alone 1.5% / 4.0% (chance 1%) | Yes, via max-of-ML into the override | No (mainly ranks rare category mixes) | Yes | **Negative** | Nominally P5 |
| **ML: LOF** (`ml/lof.py`) | Peer-scoped local density on age, hours, two earnings | → ranks | Local density | Alone 23.3% / 26.3%; max(stat+hist, LOF) lowers recall to 25.0% / 27.3% | Yes | Redundant with statistical (hours) | Yes | **None beyond statistical/historical** | P5 |
| **ML: conditional model** (`ml/conditional_models.py`) | Gradient boosting of log salaried earnings; FSU-grouped two-fold cross-fitting **within the round** | → log residual, rank | Expected earnings given characteristics | Estimate ÷ peer median 0.994 (5.5 evaluation) | Yes (max-of-ML) | Sound; not trained on history | Yes: alone 21.4% / 21.9% on 13k–17k earners | **Positive when combined by max** (+2.3 / +3.6 pp over stat+hist) | P5 (best candidate for "ML from historical data") |
| **ML: similarity** (`ml/similarity.py`) | Exact hash of ≥ 6 responses within an FSU | Informational only | Copies are exact | Duplicate-person recall 0% at 1%, 7–8% at 5% | No (correctly) | Too strict | Yes | ~0 | P4 |
| **Pattern (FSU)** (`pattern/engine.py`) | Leave-FSU-out G-test, Mann–Whitney, binomial heaping and concentration; national φ overdispersion; BH within component × variable | → `pattern_evidence.parquet` | FSUs in a stratum are exchangeable | Contradicted: 95% of pre-2025 alerts are status-mix heterogeneity | Group queue; never record risk (correct) | Partly; φ is **one value per country**; per-FSU multiplicity is uncorrected (min q over ~10 tests) | **Corrected method never evaluated**; pre-correction false alerts on clean FSUs 15.8% / 54.4% | Unknown | P4 (cluster) |
| **Historical, record level** (`historical/engine.py`) | Each value against the same cell in strictly preceding periods (4 quarters pre-2025, 3 months in 2025) | → `historical_record_evidence.parquet` | Earlier periods are a clean reference | Reference is out-of-sample (it excludes the current round, so no contamination) | Yes, weight 0.25 | Yes; nominal rupees; 3 variables | Yes: alone 35.1% / 39.5% (**best single**) | **Strong** | P3 (historical) |
| **Historical, aggregate** | Weighted LFPR/WPR/UR, median earnings, mean hours by nation/State/district × sector × period; robust z of change + SRS SE | → `aggregate_indicators.parquet` | SRS SE approximates the sampling error | Understates the design SE (clustering ignored) | UI "area trends" | Screening only | **Not evaluated** | Unknown | P4 (aggregate, temporal) |
| **Integrity** (`integrity/engine.py`, YAML) | 11 person-level rules, 6 rule types | → `integrity_violations.parquet` | Rules transcribed from manuals | 0 violations on released data (expected, post-edit) | Yes: priority = 1 | Yes | Rule injections 100% | Equals CAPI (by design) | P2 (partial) |
| **Fusion** (`fusion/engine.py`, `calibration.py`, `influence.py`) | Per-source mid-rank → weighted mean (0.30/0.20/0.25/0.25) → override ≥ 0.995 → × influence → bands 0.8/0.5/0.2 | → `fused_cases.parquet`, cards, groups | Ranks are comparable; weights reasonable; influence = importance | **Contradicted by measurement** (§5, §6) | UI queue | No | Yes: worse than its parts | **Negative** | P6 |
| **Explanation** (`fusion/explain.py`, `labels.py`) | Plain-language story from stored values | → API JSON | Faithful wording | Verified (5.5 evaluation) | UI | Yes | Not with users | High | P6 |
| **UI / API** (`fusion/api.py`, `ui/`) | Overview, list, case, decision, groups, area trends, technical reference, online check, export | — | — | Container verified on old code; **current code breaks the case page** | — | — | Not with supervisors | High once fixed | P6, P7 |
| **Review / audit** (`fusion/review.py`) | Append-only SQLite with evidence snapshot | — | Append-only by convention | 0 real decisions | Not fed back | Mutable file; the actor is free text when auth is off | No | Not yet realised | P6 |
| **Evaluation** (`evaluation/`) | 8 injection types, 1 seed, 6 States, E0–E7 | → `results/*.json` | Injected errors are representative | Stylised; 2.2% prevalence; **artefacts behind the stored JSON no longer exist** (fusion and pattern eval runs missing) | Technical reference page | Partly | — | — | P8 |

**Overall assessment.**
* The data foundation is sound: preprocessing, survey rules and provenance.
* So are the two value detectors (statistical and historical) and the explanation and audit design.
* The architecture is wrong in three places:
  1. the **priority construction** (average of ranks × influence, plus override);
  2. the **fit-and-score-on-the-same-round** design of every model, which leaves no frozen historical reference to apply to new data and so blocks both online scoring and "models from historical data";
  3. **absent schema/version control between runs and code**, which is what let the rename regression through.

---

## 4. Requirement → implementation → evidence matrix

Status vocabulary: **COMPLETE · PARTIALLY COMPLETE · NOT COMPLETE · NOT POSSIBLE WITH CURRENT DATA · IMPLEMENTED BUT NOT VALIDATED · REQUIRES HSD/eSigma INPUT**.
"Proof of completion" is the evidence a strict evaluator should accept.

### 4.1 Ingestion

| MoSPI requirement | Exact source | Current implementation | Actual evidence | Status | Gap | Required remediation | Proof of completion |
|---|---|---|---|---|---|---|---|
| Real-time ingestion through API | Feature 1: "Data ingestion in real-time (through API)" | `POST /api/validate/record`: checks 10 concept fields against rules and stored peer quantiles; **stores nothing** | Endpoint test only | **NOT COMPLETE** | No ingestion, persistence, idempotency, revision handling or incremental scoring | W7.2–W7.6: versioned ingestion API, raw zone + Postgres registry, the same scoring core as batch, mock eSigma adapter | Replaying a full release through the API gives evidence identical to batch for the same reference snapshot; idempotency and revision tests; p95 latency measured |
| Periodic batch processes | Feature 1 | `python -m pipeline.run`; Docker `batch` profile | 2025 rerun 769 s (6 Oct, on **old** code) | **PARTIALLY COMPLETE** (broken on committed code, W0.1) | No scheduler, drop zone, run QA gate or publish step | W0.1–W0.3, W7.5 | Scheduled run on a drop-zone delivery passes the QA gates and publishes; a failed gate blocks publication (tested) |
| Schema handling | Implied by F1; research doc §17 | Release contracts in `preprocessing/config.py` | Works per release; **no schema version on runs** | **PARTIALLY COMPLETE** | Code/run column drift is undetected (rename regression) | W0.1 schema registry and versioned read boundary | Legacy (`iospi_*`) and current runs both load; a mismatched schema fails loudly (tests) |
| Validation of incoming records | F1 + F3 | Online rule check (person level) | Unit tests | **PARTIALLY COMPLETE** | No household/FSU-level checks on submission; no stored outcome | W4.x rules at all levels, executed in ingestion | Every ingested household gets a stored rule outcome; injected breaches 100% detected |

### 4.2 Validation

| MoSPI requirement | Exact source | Current implementation | Actual evidence | Status | Gap | Required remediation | Proof of completion |
|---|---|---|---|---|---|---|---|
| Definable integrity checks (referential, existential, …) | Feature 3 | YAML, 11 person rules, 6 types; fixed structural checks in preprocessing | 0 violations on releases; rule injections 100% | **PARTIALLY COMPLETE** | No household/FSU/cross-table, arithmetic or code-list referential types; no UI, approval or versioning; no test cases per rule | W4.1–W4.7 | Each brief-named integrity type has a rule type, ≥ 1 cited PLFS rule, positive/negative test cases and a dry-run report on all releases; admin can author, approve and version a rule in the UI |
| Record-level validation | Objective 2 | Statistical, historical, contextual, ML | Injection study | **IMPLEMENTED BUT NOT VALIDATED** as fused (fusion < parts) | Priority loses evidence; covers 3 variables only; 60% of persons can never be prioritised | W2.x, W3.4, W4.7 | Pre-registered E6 > best single lane (§12) in both releases; coverage report shows the share of persons with ≥ 1 assessable check |
| Cluster/FSU-level validation | Objective 2: "record, cluster, and aggregate levels" | Pattern layer | Corrected method unevaluated | **IMPLEMENTED BUT NOT VALIDATED** | False-alert control unknown; no paradata; per-FSU multiplicity | W5.x | E5 meets §12 targets on every fabrication variant; clean-FSU alert rate ≤ target on real data |
| Aggregate-level validation | Objective 2; F4 | Historical aggregate screening | Not evaluated; SRS SEs | **IMPLEMENTED BUT NOT VALIDATED** | Design-based SE, seasonality and evaluation all missing | W3.6 | Injected domain shifts detected at stated power; clean false-notable rate ≤ target |
| Historical validation | Background: "use the past data" | Record and aggregate historical layer | Best single detector | **PARTIALLY COMPLETE** | 3 variables; nominal; no same-season; no frozen reference | W3.1–W3.7 | §15 acceptance criteria |
| Temporal drift | Background: "temporal drifts" | Area-level change screening; FSU-level not assessable (first-visit FSUs seen once) | 51 notable changes (2024), unevaluated | **PARTIALLY COMPLETE** | No distribution drift (PSI/JS), seasonality or known-event handling | W3.6 | Drift detection evaluated on injected shifts; seasonal comparisons where 12 months of history exist |
| Contextual validation | Background: "contextual … anomalies" | Contextual layer; peer conditioning | Weak, size-biased | **PARTIALLY COMPLETE** | Score not calibrated; mixed into the value queue | W2.5, W6.1 | Coding lane meets §12 targets |
| Related-survey validation | Background: "related survey data" | None | No data supplied | **NOT POSSIBLE WITH CURRENT DATA** · **REQUIRES HSD INPUT** | Data and concept mapping | W3.3 (CPI, public), §18 adapter | Adapter + concept-mapping spec delivered; tested on one approved dataset when supplied (G2) |
| Enumerator bias | Background: "enumerator bias" | None; FSU correctly **not** used as a proxy | No investigator ID in any layout (household files hold `Informant_Serial_No`, `Survey_Date`, `Total_Time_Taken`, no investigator code) | **NOT POSSIBLE WITH CURRENT DATA** · **REQUIRES eSigma INPUT** | ID needed | §18: contract field + dormant lane; FSU paradata as a *fieldwork* (not enumerator) signal | Lane activates and passes synthetic-ID tests; real use gated on G3 |

### 4.3 Intelligence

| MoSPI requirement | Exact source | Current implementation | Actual evidence | Status | Gap | Required remediation | Proof of completion |
|---|---|---|---|---|---|---|---|
| Statistical models | Objective 2 | Robust peer percentiles, historical percentiles, FSU tests, area screening | Strong record detectors | **PARTIALLY COMPLETE** | Leave-one-out, seasonality, design SEs | W2.9, W3.2, W3.6 | §12/§15 criteria |
| Probabilistic models | Title; Objective 2 | Empirical conditional frequency; test p-values | — | **PARTIALLY COMPLETE** | No probabilistic model of joint categorical responses; scores are uncalibrated | W2.3 (null-calibrated tail probabilities), W6.1 (categorical joint model) | Calibrated tail probabilities reproduce their nominal false-alert rate on clean history (±20% relative); W6 retained only if it passes its gate |
| ML models built from historical data | Feature 2; Objective 2 | All ML fitted **within** the scored round | — | **NOT COMPLETE** as specified | No train-on-history / score-new separation; no model registry | W3.5, W7.3 | Model trained on reference rounds and applied to the new round; registry entry with data hash, parameters and evaluation; every score traceable to a model version |
| Automated flagging, individual and aggregate | Feature 4 | Bands on a ranking; FSU alerts; area alerts | — | **PARTIALLY COMPLETE** | Bands are ranks, not calibrated flags; queue size not tied to capacity | W2.8 | Flags defined by calibrated thresholds and a workload budget; expected false-alert rate printed and verified |
| Pattern detection | Background: "unusual response patterns" | FSU tests; exact similarity | Unevaluated / ~0 recall | **IMPLEMENTED BUT NOT VALIDATED** | Near-duplicates; paradata | W5.5, W5.6 | E5 criteria |

### 4.4 Supervisor workflow

| MoSPI requirement | Exact source | Current implementation | Actual evidence | Status | Gap | Required remediation | Proof of completion |
|---|---|---|---|---|---|---|---|
| Prioritisation | Research doc §21–22; implied by F4/F5 | risk × influence | Worse than parts; small-UT distortion | **NOT COMPLETE** (functionally present, scientifically wrong) | §5–§6 | W2.1–W2.8 | §12 and §24 criteria |
| Evidence and explanation | Research doc §22 | Faithful plain-language story | Verified | **COMPLETE** for the current evidence | Must follow the new lanes | W8 updates | Explanation contract tests per lane |
| Review, decision, audit | Research doc §22 | 3 decisions, comment, append-only SQLite, snapshot | 0 real decisions; mutable file; actor spoofable when auth is off | **PARTIALLY COMPLETE** | Reason codes, field-verification outcome, tamper evidence, time-on-case | W8.2–W8.4, W7.7, W9 | Hash-chain verification test; decision taxonomy in use in the pilot |
| Feedback / learning | Research doc §22, §24 | None | — | **NOT COMPLETE** | Decisions never reach calibration | W8.4 | Recalibration report generated from recorded decisions (no automatic retraining) |

### 4.5 Outputs

| MoSPI requirement | Exact source | Current implementation | Actual evidence | Status | Gap | Required remediation | Proof of completion |
|---|---|---|---|---|---|---|---|
| Interactive **and batch** validation UI | Feature 5 | Interactive yes; batch from CLI only | — | **PARTIALLY COMPLETE** | Start, monitor and publish a batch from the UI (admin) | W8.7 | UI-triggered run passes the QA gates and appears in the run list |
| Dashboards on performance metrics | Feature 6 | Overview, area trends, technical reference | — | **PARTIALLY COMPLETE** | Workload, progress, decision outcomes, alert-rate and drift monitoring | W8.5 | Dashboard spec items present with numbers equal to independent SQL |
| Export / reporting | Feature 7 | Streamed CSV | 415,549 rows verified | **PARTIALLY COMPLETE** | Excel/PDF; supervisor-wise, geographic, rule and FSU reports; export permission and logging | W8.6, W9 | Reports reconcile with the database; export logged and role-gated |

### 4.6 Engineering

| MoSPI requirement | Exact source | Current implementation | Actual evidence | Status | Gap | Required remediation | Proof of completion |
|---|---|---|---|---|---|---|---|
| Modular, general-purpose platform | Objective 1; background | Modular packages; PLFS mappings hard-coded in ≥ 5 modules | — | **PARTIALLY COMPLETE** | Survey pack | W10.1 | A second schedule is onboarded via configuration only (adapter code ≤ one module) |
| Scalability | Note 1 | Single node; 2025 batch 769 s (reused stages), first run 5,713 s | Measured | **PARTIALLY COMPLETE** | Incremental scoring; the historical stage took 64 min | W7.3, W3.1 | Full 2025 batch ≤ 30 min on 8 cores; online p95 ≤ 1 s/household |
| Cloud readiness | Note 1 | Docker, hardened container | Verified (old image) | **PARTIALLY COMPLETE** | Stateless app + Postgres + object store; config by environment; health/readiness | W7.1 | Deployed from the compose/K8s manifest on a clean host from the docs |
| Security, confidentiality | Note 2 | Prototype controls | §13 of 5.5 | **NOT COMPLETE** · **REQUIRES MoSPI INFRASTRUCTURE/POLICY** | §19 | W9.x | Control matrix with test evidence; MoSPI security review sign-off (G4) |
| Open source, low cost | Note 1 | Python stack | — | **COMPLETE** | Keep it so (Postgres, MinIO optional) | — | SBOM with licences |
| Evaluation from 2024 onwards | Objective 3 | Injection E0–E7 on 2024 and 2025 | Single seed; metric artefact; artefacts missing | **PARTIALLY COMPLETE** | §12 | W1.x | Pre-registered protocol executed; results reproducible from stored artefacts |
| Training | Objective 4 | None | — | **NOT COMPLETE** · delivery **REQUIRES HSD** | Material can be built now | W11.1 | Training pack + exercise set with answer key; session delivered (G6) |
| eSigma roadmap | Objective 5 | Narrative roadmap | — | **PARTIALLY COMPLETE** | Interface specification, sequence, security, open questions | §20, W7.2 | OpenAPI spec + boundary document reviewed by eSigma team (G5) |

---

## 5. Complete scientific audit

### 5.1 Survey design handling: keep

* **Correct:** applicability gating, documented final weights, the release-overlap de-duplication (`historical.deduplicate_periods`), the January-2025 boundary, first-visit/revisit separation and no cross-release person linkage.
* **Gaps:**
  * Pre-2025 peer groups pool four quarters (a seasonality gap; `peer_groups/config.py`).
  * Weights are not used to judge records. That is correct for validation, but weights matter for impact (§5.8).

### 5.2 Statistical layer: keep and refine

* The percentile is a robust, distribution-free description and the detector works: 33.4% / 31.3% alone.
* **Defect S1: self-inclusion.** `add_distribution_evidence` ranks a value within a group that contains it, and computes the median and MAD with it included. Current-round errors also contaminate the reference.
  * Effect: a modest underestimate of extremity in small groups.
  * The historical layer, whose reference is out-of-sample, beats it on 2025 (39.5% vs 31.3%), consistent with contamination mattering.
  * Fix: leave-one-out placement (W2.9).
* **Defect S2: the bounded score.** `|percentile − 0.5| × 2` cannot exceed `1 − 1/n`. In a group of 30 the highest possible score is 0.967, while large groups reach 0.9998, so global ranking favours records in large groups.
  * Measured: the clean top 1% have median group size 115 vs 130 overall (2024): small but present.
  * Fix: convert to a tail probability with a finite-sample correction (W2.3).
* **Finding S3: naive magnitude scoring is worse.** A log-scale robust z (`|ln(1+y) − ln(1+median)| / (log-IQR/1.349)`) gives only 3.1% / 2.6% top-1% recall. Groups with near-zero spread produce enormous z for ordinary values.
  * **Do not "fix" the ranking by switching to raw magnitude.** Any magnitude-preserving score must be tested in the harness first.

### 5.3 Historical layer: the strongest asset, make it first-class

* An out-of-sample reference: earlier periods only, so it is uncontaminated by current-round errors. The best single detector: 35.1% / 39.5%.
* Spearman with statistical is 0.94 / 0.90, so the two are highly redundant. Their **average still beats both** (39.7% / 38.0%), because they disagree mainly on contaminated or seasonal cases.
* **Limits:**
  * three variables only;
  * nominal rupees;
  * no same-season comparison;
  * reference rebuilt per run, not frozen;
  * 2025 compares only with three earlier 2025 months.
* **Aggregate screening:** SRS SEs understate the true SE by roughly √(design effect), so the screen is liberal; not evaluated. Details in §15.

### 5.4 Contextual layer: demote to a separate "coding check" list

* On value errors its scores are noise (mean rank 0.547 / 0.559). Averaging it into risk costs **7.7 / 9.9 pp** of top-1% recall: current minus contextual gives 29.4% / 27.7%, against 21.7% / 17.8%.
* It is the only detector for occupation miscodes: 38.7% / 27.3% at 1%.
* Surprisal depends on reference size: unique codes in large groups score higher.
* Fix (W2.5):
  * a tail probability of the observed code count under a Dirichlet-smoothed conditional distribution;
  * in its own lane, with its own small budget.

### 5.5 ML layer, model by model

| Model | Problem solved | Relevant? | Features valid? | Survey design? | Missing / N/A | Leakage? | Reference valid? | Interpretable? | Measured value | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| Isolation Forest | Generic multivariate rarity | Weakly: rarity ≠ error | Coarsened categories; 25 trees, 10k rows | Bounded by release/visit/month | N/A as missing + indicator (OK) | No | Includes current errors | "Unusual pattern" only | Alone 1.5% / 4.0% at 1% (chance 1%); 65% of ML top-1% | **Remove from priority** → optional research output |
| LOF (peer) | Local density in age, hours, earnings | Overlaps statistical | OK | Peer-scoped | Includes non-applicable zeros as values (`ml/lof.py`) | No | Current round | Poor | Alone 23.3% / 26.3%; lowers stat+hist when combined | **Remove from priority** (redundant) |
| Conditional model | Expected salaried earnings given characteristics | **Yes**: "plausible for this person" | Sound | State and sector as predictors (appropriate) | Applicable earners only | No (cross-fitted, FSU-grouped) | Current round (should be history) | Yes ("model estimate ₹X") | Alone 21.4% / 21.9% on salaried only; max-combination +2.3 / +3.6 pp | **Keep and promote**: train on history, add quantile intervals, extend to self-employment, casual wages, hours |
| Exact similarity | Copied responses | Yes | Too strict (exact hash) | Within FSU | — | No | — | Yes | 0% / ~7% duplicate recall | **Replace** with near-duplicate household/person detection as a group signal (W5.6) |

### 5.6 Pattern (FSU) layer: re-evaluate, then fix

| Check | Verified |
|---|---|
| **Directionality** | Direction is now correct: Mann–Whitney wording follows the medians; heaping and concentration are one-sided and say "higher" or "less" only when true. |
| **JS distance** | `_js_distance` is stable when a category is absent. It is now display-only (the test uses G). |
| **Concentration / tie handling** | The binomial test of the share within ±IQR/2 handles ties exactly. Centring on the FSU's own median makes small-FSU p-values optimistic (documented, unfixed). |
| **Small FSUs** | Minimum 10; G-test with Williams correction. Approximate for 10–20 persons; exact or Monte Carlo would be better. |
| **Reference population** | Leave-FSU-out within release × visit × month × State × sector × stratum. It ignores age/sex composition, so the status mix differs whenever demography differs. That is the likely cause of "95% status-mix alerts". |
| **Zero earnings** | Applicability-filtered; genuine applicable zeros retained (correct). |
| **Negative or invalid scores** | `-log10(p)` with a floor; no negatives found. |
| **Overdispersion φ** | **One φ per component × variable for the whole country.** Heterogeneity differs by State and sector, so φ over-corrects homogeneous areas and under-corrects heterogeneous ones. A likely reason 2025 dropped to 27 alerts from 13,314 FSUs. |
| **Multiplicity** | BH runs within each component × variable. The FSU group score then takes the **minimum q over ~10 tests**, so the FSU-level FDR is not controlled. |
| **Temporal** | First-visit FSUs are observed once, so correctly "not assessable". |
| **Group → individual** | Correctly prevented: pattern is not in record risk, and fabricated-FSU members' mean risk is 0.454 vs 0.435. |
| **Evaluation** | The corrected method was **never evaluated**, and the fusion/pattern evaluation artefacts were deleted, so the stored JSON cannot be re-derived. |

### 5.7 Fusion and prioritisation

Traced chain: source evidence → per-source rank → weighted mean → override → risk → × influence → priority → bands.

| Step | What happens | Measured consequence |
|---|---|---|
| Per-source rank (`percentile_midrank`) | Each source ranked across the whole run | Magnitude lost (acceptable). Ranks of sources blind to an error type are uniform noise. |
| Weighted mean | Averages ranks of detectors that look at **different variables** | Dilution: contextual costs 7.7 / 9.9 pp; ML (as max of 3) costs 1.7 / 3.9 pp |
| Max-of-ML (`_ml`: `groupby.max`) | The maximum of 3 method ranks is biased upwards | Isolation Forest dominates the ML score (65% of the ML top 1%) |
| Override ≥ 0.995 | One extreme source sets risk | Lifts IF and contextual noise into CRITICAL: 24.5% of CRITICAL is override-driven (891 ML, 158 contextual) |
| × influence | `w·|y − m| / Σ_domain w·|y|` over State × sector × period | Correlates with risk at 0.59 (double counting). Spearman with domain size −0.34. **CRITICAL share 20.4% (Lakshadweep) vs 1.15% (UP).** |
| Rule records → priority 1 | Correct to review, but evaluated in the same top-K | Created the 10.3% metric artefact |
| Bands 0.8 / 0.5 / 0.2 | Fixed cut points on a product of two ranks | ~1.4% of records CRITICAL by construction, regardless of data quality |

### 5.8 Influence and impact

The idea of prioritising by impact on estimates (selective editing) is legitimate. The implementation measures the wrong thing:
* Shares of **State × sector totals** reward small domains.
* "Total" is not the published estimand; PLFS publishes rates and averages.
* Multiplying impact by risk turns a review list for errors into a list of large-weight records.

Redesign (W2.7):
* Compute impact as the change in the **domain's published-type estimate** when the value is replaced by its expected value, for example the weighted mean earnings of the domain, or LFPR when status is involved. Divide that change by the **standard error of that estimate**.
* The result reads "this value alone moves the estimate by 0.4 standard errors". It is comparable across domains, because small domains have large SEs.
* Use it **only** to order cases within the same evidence tier, and as a filter. Never multiply it into the evidence score.

### 5.9 Explanation, review and audit

The explanation layer is a genuine strength and stays. It needs:
* new lane-aware templates;
* reason codes for decisions;
* a tamper-evident audit (hash chain, W7.7/W9.6);
* role-bound actors (free-text actors are accepted when auth is off: `fusion/api.py:334`).

### 5.10 How the new numbers were produced

* A read-only script loaded the stored evaluation evidence: `evaluation/runs/{2024,2025}_injection/{statistical,historical,contextual,ml,integrity}` and the injection labels. It wrote nothing to the repository.
* It rebuilt per-record raw scores exactly as `fusion/engine.py` does: statistical `max |pct − 0.5| × 2`; historical `max historical_score`; contextual surprisal; ML `max evidence_rank`.
* It called the unmodified `FusionEngine.fuse` with the experiment weights.
* It evaluated each ranking on the **CAPI-pass population**: all records minus those with a rule error and minus the two rule-injection types. That gives 2024 n = 106,481 with 1,773 injected; 2025 n = 150,049 with 1,778.
* Ties were broken by the same stable hash as `evaluation/run.py`.
* CIs: 500 bootstrap resamples of the injected records.
* Influence diagnostics used `fusion/runs/2024_first_visit_v2/fused_cases.parquet`.

**W1.8 turns this script into `evaluation/diagnostics.py`**, so every number in this plan is regenerated by a committed command.

---

## 6. The 5.5 evaluation, finding by finding

**Category key:** M = methodology, I = implementation, E = evaluation, D = data limitation, A = architecture.

| ID | Finding (5.5) | Still valid? | Exact cause | Category | Correct fix | Test | Success evidence |
|---|---|---|---|---|---|---|---|
| **C1** | Fused priority worse than single components; headline 73.1% is a rules artefact | **Valid, magnitude restated**: 21.7% / 17.8% fair (not 10.3% / 11.9%); the 73.1% artefact is confirmed | (a) mean of ranks dilutes type-specific evidence; (b) IF via max-of-ML + override; (c) contextual size bias; (d) × influence reorders by domain size; (e) metric mixes rule records into the same top-K | M + E | W2.1–W2.8 lanes; W1.3 CAPI-pass metric | E1–E7 multi-seed, paired bootstrap | Pre-registered: E6 ≥ best single + 3 pp R@1% (CI of the paired difference excludes 0), both releases |
| **C2** | Real-world effectiveness not establishable | **Valid** | Post-edit released data; no labels; 0 decisions | D | Pilot with HSD on pre-scrutiny eSigma data + a random audit sample (§12.7) | Pilot protocol | Confirmed-issue rate among flags and audit-estimated miss rate with CIs (G1) |
| **H1** | No real-time ingestion | Valid | Never built; scoring is fitted per round, so nothing can be applied to new data | A | W7.2–W7.6 + frozen reference snapshots (W3.1) | API/batch equivalence | Identical evidence via API vs batch |
| **H2** | Related surveys and enumerator not assessable | Valid | No data / no ID | D | §18 adapters; dormant enumerator lane; FSU paradata as a fieldwork signal | Synthetic-ID tests | Gated (G2, G3) |
| **H3** | Integrity facility person-level, file-only | Valid | Rule engine has 6 person-level types | A | W4.1–W4.7 | Rule tests, dry-runs | §16 criteria |
| **H4** | FSU corrected method unevaluated; status-mix dominated; 27 alerts in 2025 | Valid, plus new defects (national φ, per-FSU multiplicity, no composition adjustment) | §5.6 | M + E | W5.1–W5.7 | E5 | §13 criteria |
| **H5** | ML and contextual reduce fused performance; override lets one source dominate | **Valid but refined**: the *conditional model* helps when max-combined; IF is the harmful part | Mean-of-ranks + max-of-ML + override | M | W2.4–W2.6 | E4, E7 | Each retained component passes its ablation gate |
| **H6** | risk and influence double-count (r = 0.60) | Valid (0.59) **and worse**: small-UT distortion | Domain-share influence | M | W2.7 impact ÷ SE, ordering only | State burden test | Max/median State flag rate on clean data ≤ 3 |
| **H7** | Security prototype level | Valid | Not built | A + policy | W9.x | Control tests | §19 matrix; G4 |
| **H8** | Not survey-general | Valid | PLFS maps in Python | A | W10.1 | Second-schedule onboarding | Config-only onboarding |
| **H9** | No learning from decisions; no registry | Valid | Not built | A | W8.4, W7.1 registry | Recalibration report | Report produced from decisions |
| **H10** | 2025 missing from the tool (fixed) | Fixed then, but **the class of defect remains**: nothing detects an empty or degraded stage | No run QA gate | I | W0.3 | Fault injection | Pipeline fails on an empty or degraded stage |
| M1 | Contextual size dependence | Valid (measured: 1,353 vs 324) | Raw surprisal | M | W2.5 | E2 | Coding-lane criteria |
| M2 | Pre-2025 peer groups pool quarters | Valid | Peer spec | M | W2.9 quarter boundary (with backoff) | E1 per quarter | No loss of recall; seasonal FP reduction reported |
| M3 | IF under-powered | Superseded: IF is removed from priority | — | M | W2.4 | E4 | — |
| M4 | Area screening liberal | Valid | SRS SE | M | W3.6 | E5-aggregate | Clean false-notable rate ≤ 5% |
| M5 | 60% of persons can never be prioritised | Valid | 3 numeric targets; influence required | M + A | W2.1 (no influence gate), W3.4, W4.7, W6.1 | Coverage report | ≥ 90% of persons have ≥ 1 assessable non-rule check (status/time-disposition consistency covers non-workers) |
| M6 | Revisit evidence not in the list | Valid | Not wired | I | W2.10 revisit lane (2023-24; future panels) | E1 on linked records | Revisit change lane evaluated |
| M7 | Single seed, 6 States, no CIs; duplicates undetected | Valid | Evaluation design | E | W1.x, W5.6 | — | §12 |
| M8 | Stale docs | Partly fixed | — | I | W0.6 doc regeneration from run metadata | Doc link check | Docs reference existing artefacts only |
| M9 | Unpinned requirements | Fixed | — | — | Add hash-pinned lock + CVE scan (W9.10) | — | — |
| M10 | Batch not from UI; historical 64 min | Valid | — | A | W8.7, W3.1 | Timing | ≤ 30 min full 2025 |
| M11 | CSV only | Valid | — | I | W8.6 | Reconciliation | — |
| L1–L6 | Wording, V1 runs, writable read path, warnings, storage keys, phone width | Valid (low) | — | I | W8 polish; L3 → read-only DB connection on reads | — | — |

**New findings from this audit** (not in the 5.5 evaluation):

| ID | Finding | Evidence | Severity |
|---|---|---|---|
| **N1** | Rename regression: committed code reads `MoSPI_*`, stored runs hold `iospi_*`. Case page, fusion, evaluation, statistical, ML and pattern break on real data. | BinderException; FusionFailure; container has 22 `iospi_` files vs 0 in the repo | **CRITICAL** |
| **N2** | Silent degradation: `historical.load_release` fills missing columns with `""`. A rerun would publish all-not-assessable evidence without error. | All 415,549 records: blank State, sector, period; `ready = False` | **CRITICAL** |
| **N3** | Evaluation not reproducible: fusion and pattern evaluation runs are absent, so `results/*.json` cannot be re-derived | `evaluation/runs/*` lacks `fusion/`, `pattern/` | HIGH |
| **N4** | Metric artefact: rule injections occupy top-K slots, capping non-rule recall at 26.6% (2024) | k = 1,071 slots, 600 rule records | HIGH |
| **N5** | Influence favours small domains: CRITICAL share 20.4% (Lakshadweep) vs 1.15% (UP) | §5.7 | HIGH |
| **N6** | Isolation Forest near chance yet dominant via max-of-ML | 1.5% / 4.0%; 65% of ML top-1% | HIGH |
| **N7** | Rich data unused: interview duration (`Total_Time_Taken` / `sur_time`, median 60 min), `Survey_Date`, 7-day time disposition and daily wages (22,178 casual workers with day-7 wages, 2024), consumption, response/substitution codes, relationship to head | Schema listing and queries | HIGH (opportunity) |
| **N8** | FSU multiplicity and national φ (§5.6) | Code | MEDIUM |
| **N9** | Statistical reference includes the observation and current-round errors | Code | MEDIUM |
| **N10** | Export is not role-restricted; audit actor spoofable when auth is off (the default) | `fusion/api.py` | MEDIUM (HIGH for pilot) |
| **N11** | Candidate integrity relations not yet documented. Day-7 total ≠ act1 + act2 hours for 9,962 (2024) and 25,766 (2025) persons, 97% "total < sum", apparently because non-work codes such as 62 carry hours. `hce_tot ≠ Σ hce1–5` for 269,694 of 270,472 households, probably annual items /12. These must be transcribed from Vol. I before becoming rules. **2025 `tothrs_wrk = Σ hr1–hr7` holds for all 1,148,634 persons**, so it is a validated hard rule. | DuckDB queries | MEDIUM |

---

## 7. Root causes of the current weaknesses

1. **No measurement contract before design.** Fusion weights, override and bands were set by intuition, and the evaluation came afterwards with a metric that mixed rule records into the same top-K. *Remedy:* pre-registered protocol and CAPI-pass metric **before** any method change (Phase 1).
2. **Wrong combination operator.** Detectors look at different variables, so evidence is "OR-like" across variables and "AND-like" only across references of the *same* variable. The current design averages everything, and caps only through an override. *Remedy:* combine per variable (current peers + history + expected value), then take the maximum across variables with a calibrated null (Phase 2).
3. **ML kept for its label, not its contribution.** IF and LOF entered priority without passing an ablation gate. *Remedy:* every component must earn its place in E4/E7 (§14).
4. **Importance confused with suspicion.** risk × influence mixes "is it wrong?" with "does it matter?", and influence was defined on unequal domains. *Remedy:* separate dimensions; impact ÷ SE used for ordering only.
5. **Fit-and-score-in-the-same-round architecture.** It blocks online scoring, "models from historical data" and a stable calibration, and lets current-round errors contaminate references. *Remedy:* frozen, versioned reference snapshots built from approved rounds; a pure scoring core (Phases 3, 7).
6. **No schema or run contracts across layers.** Column names, required fields and assessability rates are not checked, so a global rename and a silently empty stage both passed tests. *Remedy:* schema registry, fail-loud readers, run QA gates and a real-data smoke test (Phase 0).
7. **Narrow variable coverage.** Three numeric targets cover 40% of persons, and paradata and household data are unused. *Remedy:* coverage expansion through validated rules, consistency models and new variables (Phases 3–6).
8. **The evaluation does not reflect operations.** 2.2% prevalence, stylised errors, one seed, six States, no workload or false-alert burden on real data. *Remedy:* §12.

---

## 8. Target scientific architecture

### 8.1 Principle: separate lanes; never average across error mechanisms

```
                      ┌──────────────────────────────────────────────────────────┐
 submission/batch ──► │ L0  Integrity rules (hard / soft; person, household, FSU) │──► Rule findings list (always reviewed; never mixed into scores)
                      └──────────────────────────────────────────────────────────┘
                      ┌──────────────────────────────────────────────────────────┐
                      │ L1  Value plausibility, per variable v:                   │
                      │     current peers (leave-one-out)  ┐                      │
                      │     historical reference (frozen)  ├─ per-variable evidence e_v
                      │     expected value (conditional model trained on history) ┘
                      │     record value score = max_v calibrated tail evidence   │──► Value-check list
                      └──────────────────────────────────────────────────────────┘
                      ┌──────────────────────────────────────────────────────────┐
                      │ L2  Coding plausibility (occupation/industry | context),  │──► Coding-check list (own small budget)
                      │     smoothed conditional tail probability                │
                      └──────────────────────────────────────────────────────────┘
                      ┌──────────────────────────────────────────────────────────┐
                      │ L3  Cross-item consistency (status / time disposition /   │──► Consistency list (research gate W6)
                      │     education / age), probabilistic model from history    │
                      └──────────────────────────────────────────────────────────┘
                      ┌──────────────────────────────────────────────────────────┐
                      │ L4  FSU / household-group patterns + fieldwork paradata   │──► Group alerts (never individual error claims)
                      └──────────────────────────────────────────────────────────┘
                      ┌──────────────────────────────────────────────────────────┐
                      │ L5  Area / aggregate & temporal drift vs history          │──► Area alerts (bulletin pre-check)
                      └──────────────────────────────────────────────────────────┘
          Impact annotation (Δ estimate ÷ SE): ordering within a tier + filter only
          Workload budget (per supervisor / FSU / day): sets list length
```

### 8.2 Calibration: tail probabilities against a frozen clean reference

* For each lane score s, compute `p = P(S ≥ s)` under the **reference round's score distribution**. The reference round is the last approved round, scored the same way. The score is not ranked within the current run.
* Consequences:
  * a stable meaning across rounds ("fewer than 1 in 1,000 comparable records last round looked like this");
  * no forced 1.4% CRITICAL share;
  * a quiet round produces a short list;
  * a degraded round is visible.
* Record-level multiplicity across variables: apply a Šidák-style correction for the number of variables assessed (or the Cauchy combination). Variable-rich records are then not flagged more often by chance.
* **Expected false alerts per 1,000 clean records = the chosen threshold × 1,000.** This is verified on clean released data (§12.6).

### 8.3 Queue construction

* **Tier A, "Check now":** rule findings, plus records whose best lane evidence passes the threshold set by the HSD-supplied workload budget (default: review capacity × days ÷ records).
* **Tier B, "Check if time":** the next band of evidence.
* **Within a tier:** order by impact ÷ SE, then by evidence.
* **FSU grouping:** cases are presented grouped by FSU and household, because verification is done per household visit or call. The per-FSU cap is configurable.
* **Coding lane:** a fixed share of the budget (default 10%, to be set from E2). Measured on stored evidence: a 10% share costs 2.2 / 1.7 pp overall top-1% recall and recovers occupation miscodes. This is a policy choice for HSD, shown explicitly.

### 8.4 Candidate designs to compare under the protocol (pre-registered)

| Code | Design | Stored-evidence indication (top-1% recall, CAPI-pass) |
|---|---|---|
| A0 | Current fusion (baseline) | 21.7% / 17.8% |
| A1 | Current fusion, IF and LOF removed, contextual removed | to be measured |
| B | Mean of statistical and historical ranks | 39.7% / 38.0% |
| C | max(B, conditional-model rank) | 42.0% / 41.6% |
| D | C with per-variable combination and null calibration (§8.2) | to be measured |
| D+L | D with coding lane at 10% | to be measured (~37.5% / 36.3% for B + 10%) |
| D+L+W6 | D+L with the categorical consistency lane, if W6 passes | to be measured |

**The selection rule is fixed in advance:**
* Choose the **simplest** design whose confirmation-set recall is not significantly below the best design: paired bootstrap, one-sided α = 0.05, margin 2 pp.
* Its precision must also be ≥ the best single lane, and it must meet the burden and fairness criteria in §12.5.

---

## 9. Target production architecture

```
 eSigma/CAPI ──(phase-dependent)──►  Ingestion adapter  ◄── mock adapter (replay of a PLFS release by survey date)
                                           │  OpenAPI v1, service auth, idempotency key, schema version
                                           ▼
                                  Raw zone (immutable files, hashed)  +  ingestion registry (PostgreSQL)
                                           │
                                  Schema & applicability contract (survey pack)
                                           │
                                  L0 integrity rules (versioned rule registry)
                                           │
                                  Survey-design assignment (design period, period, peer & reference cells)
                                           │
                                  Reference lookup ── frozen reference snapshot (versioned; built from approved rounds)
                                           │
                       ┌───────────── scoring core (pure functions; same code online and batch) ─────────────┐
                       │  L1 value  ·  L2 coding  ·  L3 consistency  ·  L4 group  ·  L5 area                  │
                       └────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                  Calibration (tail probabilities vs reference) → queue builder (budget, tiers, FSU grouping)
                                           │
                                  Case store (PostgreSQL) ──► Supervisor UI / API ──► decisions (hash-chained audit)
                                           │                                              │
                                           └────────── feedback: decision-based recalibration report ◄┘
```

**What we can implement with the current PLFS files:**
* everything above, with the **mock adapter** standing in for eSigma;
* reference snapshots from 2023-24 / 2024 (pre-2025 design) and from 2025 months (post-2025 design);
* replay of releases to test online/batch equivalence.

**What requires HSD/eSigma access:**
* the real connector (endpoint, authentication, field mapping, revision semantics);
* pre-scrutiny data;
* investigator IDs;
* the identity provider;
* hosting.

These are external dependencies, never simulated as real.

**Deliberately not adopted now** (research document §26 lists them):
* **Kafka:** submission volumes are well below one message per second averaged over a year (≈ 270k households/year in 2025); an HTTP API with a Postgres queue suffices.
* **Spark:** 1.15M persons/year fits in DuckDB/pandas on one node.
* **Airflow:** a scheduled job with run QA gates suffices.
* **Kubernetes:** Compose on one approved VM is enough for a pilot.

Each has a documented trigger for adoption, for example more than 10 surveys or more than 50M rows/year (§30 of the research document is satisfied by design, not by infrastructure).

---

## 10. Target data architecture

What the application actually reads today: Parquet runs via DuckDB (`fusion/api.py`, `fusion/explain.py`), SQLite audit per run, JSON reports.

| Data | Store | Why |
|---|---|---|
| Raw deliveries/submissions | Object store (filesystem or S3-compatible MinIO), immutable, SHA-256 named | Provenance; re-processing |
| Prepared, evidence and reference snapshots | Parquet in the object store, partitioned by survey/release/design period/period | Analytical scans; DuckDB reads in place; 2025 ≈ 1–2 GB |
| Ingestion registry (batches, submissions, revisions, schema versions) | **PostgreSQL** | Transactions, idempotency, revision supersession |
| Case store (current queue materialisation, tier, lane, evidence summary) | **PostgreSQL** | Filtering, paging, assignment, concurrency between supervisors |
| Decisions and audit events | **PostgreSQL**, append-only table with hash chain, `INSERT`-only DB role, periodic signed digest | Tamper evidence; multi-user |
| Rule registry, survey packs, thresholds, budgets | PostgreSQL (versioned rows) + exported YAML for review | Approval workflow |
| Model/reference registry (version, data hashes, parameters, metrics, approver) | PostgreSQL + artefact files in the object store | Research doc §24 traceability |
| Access and export logs | PostgreSQL + shipped to MoSPI log store | CERT-In-style retention (§19) |
| Cache | In-process LRU for reference lookups; no Redis until measured need | Simplicity |

**Migration:**
* Existing SQLite audit events are copied once into Postgres with their original timestamps, and a migration record per file holds its hash.
* Parquet stays where it is.
* **No destructive migration.**

---

## 11. Target supervisor workflow

1. **Open the workspace:**
   * "My area: 42 cases to check this week (rule findings 3, value checks 33, coding checks 6), 2 group alerts, 1 area alert."
   * Progress against the budget is shown.
2. **Work list:** grouped by FSU → household. One line per case, with the plain reason ("monthly salary ₹1,50,000 is about 10× what similar workers earned here this quarter and last year").
3. **Case page, top to bottom:**
   * **what was recorded** (the person's relevant answers);
   * **current comparison** ("9 in 10 similar workers in rural Bihar, Q3 2024: ₹6,000–₹22,000; n = 412");
   * **historical comparison** ("same group, Q3 2023: ₹5,500–₹20,000"; "last 4 quarters: …");
   * **expected value** ("for a person with these characteristics: about ₹14,000; usual range ₹8,000–₹25,000");
   * **group context** (if an FSU alert exists: "this FSU also shows …; this does not mean this answer is wrong");
   * **importance** ("on its own this value moves the district's average salary by 0.6 standard errors");
   * **what to verify** (concrete item and schedule reference; likely keying patterns: extra zero, annual vs monthly, digit swap).
4. **Decide**, with reason codes:
   * *Confirmed error*, with the corrected value if known and the source: call, revisit, schedule image;
   * *Valid but unusual*, with the reason;
   * *Needs field verification*;
   * *Cannot verify*;
   * *Escalate*.
5. **Next case**, staying in the same household or FSU first.
6. **Technical details** stay behind a toggle for statisticians. A supervisor never needs scores, ranks or model names.

**Usability targets:**
* median time per case ≤ 2 minutes for value checks, measured;
* ≥ 90% of proxy users complete the five core tasks unaided (W8 test).

---

## 12. Evaluation redesign

### 12.1 The question

Does the platform find useful problems that deterministic CAPI validation would miss, within a realistic review budget and at a tolerable false-alert burden?

### 12.2 Experiments

| ID | Ranking | Population | Purpose |
|---|---|---|---|
| E0 | Rules only | All records | What CAPI-style rules catch (should equal the rule-type injections) |
| E1 | Statistical lane alone | **CAPI-pass** | Additional non-rule errors |
| E2 | Historical lane alone | CAPI-pass | Value of past data |
| E3 | Contextual/coding and consistency (W6) lanes | CAPI-pass, coding/consistency errors | Contextual value |
| E4 | Each ML model alone and added to the best non-ML design | CAPI-pass | ML contribution |
| E5 | FSU lane; area lane | FSUs; domains | Group and aggregate detection |
| E6 | Combined design (candidates §8.4) | CAPI-pass + rule list reported separately | Does the combination beat the parts? |
| E7 | E6 minus each component | CAPI-pass | Ablation; a component stays only if removing it lowers recall (paired CI excludes 0) or an independently justified operational reason is documented |

**Headline metrics are always CAPI-pass.** Rule findings are reported as their own list with their own recall: they should be 100%, being deterministic.

### 12.3 Error catalogue (`evaluation/catalogue.py`)

| Level | Type | Parameters |
|---|---|---|
| Record, value | ×10, ÷10, ×100, ÷100; **×12 / ÷12 (monthly vs annual)**; digit transposition; digit drop/duplication; **plausible-but-wrong** (a value drawn from the 80th–97th percentile of a *different* comparable cell) | magnitude ∈ {mild, moderate, gross} |
| Record, hours | +10 keying; day-total ≠ activity sum; hours on a non-working day | — |
| Record, coding | Occupation miscode (same major group / different); industry miscode; status swaps that remain rule-valid (for example 31 ↔ 11 with consistent earnings) | — |
| Record, cross-item | Education level vs age (soft); usual vs current status contradiction; casual worker with salaried earnings pattern | — |
| Household | Copied household within an FSU; household size vs persons (structural); head missing/duplicated | — |
| FSU | Age heaping only; constant earnings; copied households; reduced variance; **short interview durations; all interviews on one date**; mixtures | share of FSU households affected ∈ {50%, 100%} |
| Area / temporal | +10% / +20% shift of district-month earnings; LFPR shift of 3 / 5 pp | domain size strata |
| Prevalence | Record errors at 0.2%, 0.5%, 2% of records | — |

### 12.4 Design

* **Seeds:** 20 per release. Seeds 1–5 for **development**, 6–20 for **confirmation**; confirmation results are produced once, after the design is frozen.
* **States:** all States/UTs in two folds (A for development, B for confirmation), balanced by size and region. Every comparison is State-bounded, so folds are independent.
* **Releases:** 2024 (with 2023-24 history); 2025 (Feb–Dec injected, Jan as reference).
* **Every run stores** the git commit, data hashes, catalogue version, seed and all artefacts (fixes N3).

### 12.5 Metrics and acceptance (pre-registered in `evaluation/PROTOCOL.md`)

| Metric | Definition | Target for the final design |
|---|---|---|
| R@K, P@K, F0.5@K | K = 0.5%, 1%, 2%, 5% of the CAPI-pass records, and K = workload budget | E6 R@1% ≥ best single lane + 3 pp; paired-bootstrap 95% CI of the difference > 0 in **both** releases |
| AP, PR curve | sklearn AP; full curve stored | Reported with CIs |
| Per-type recall | By catalogue type and magnitude | No type with recall below chance at 5%, except where documented as undetectable |
| Prevalence sensitivity | Precision at prevalence 0.2 / 0.5 / 2% | Reported (precision is prevalence-dependent) |
| Subgroup stability | R@5% by State, sector, design period | No State below 50% of the national R@5% where n_injected ≥ 30 |
| **Burden on real data** | Tier-A flags per 1,000 records on the *real* released data, by State | Within ±20% of the calibrated expectation; max/median State rate ≤ 3 |
| FSU/group | Recall per fabrication variant; clean-FSU alert rate | Clean alert rate ≤ 2%; per-variant recall reported with CI |
| Aggregate | Power by shift size and domain size; clean false-notable rate | Clean false-notable ≤ 5% |
| Rank stability | Kendall τ of tier membership between seeds without injections (i.e. code determinism) and between adjacent months | τ = 1 for reruns; month-to-month burden stable ±25% |
| Calibration | Observed vs nominal tail rate on clean held-out rounds | Ratio within 0.8–1.25 |
| Cost | Wall time and peak memory per stage | Full 2025 batch ≤ 30 min, ≤ 6 GB |
| Workload | Cases per FSU; cases per supervisor-day at the HSD budget | Reported; budget configurable |

### 12.6 Real-data burden check

Run the final design on the full real releases, which are clean in the CAPI sense, and report Tier-A rates. A rate far above the calibrated expectation means the calibration is wrong. It does **not** mean the released data are full of errors.

### 12.7 Pilot protocol (gated, G1)

* With HSD, on pre-scrutiny eSigma data for a sample of FSUs:
  * supervisors review Tier A;
  * they also verify a **random audit sample of unflagged records** (for example 200), so that real recall can be estimated as 1 − (errors found in the audit / errors expected).
* Report:
  * confirmed-issue rate per lane (true precision);
  * audit-estimated miss rate with exact binomial CI;
  * time per case;
  * inter-reviewer agreement on a double-reviewed subset (Cohen's κ).

---

## 13. FSU / pattern remediation

| Step | Change | Files | Test / evaluation | Acceptance |
|---|---|---|---|---|
| W5.1 | **Evaluate the current corrected method first** (baseline) | `evaluation/` | E5 on 20 seeds | Numbers published before any change |
| W5.2 | Per-FSU combination: combine the FSU's component p-values with the Cauchy combination test (valid under dependence), then apply BH across FSUs; the group band uses the FSU-level q | `pattern/engine.py: _rank`, `fusion/engine.py: _groups` | Null simulation (permuted FSU labels): FSU-level FDR ≤ nominal | FDR within nominal ±1 pp |
| W5.3 | Local dispersion φ per State × sector (fallback national when < 30 FSUs) | `overdispersion_adjust` | Clean-FSU alert rate by State | ≤ 2% overall; no State > 5% |
| W5.4 | Composition-adjusted status mix: expected counts from reference age × sex-specific status rates (indirect standardisation), G-test on observed vs expected | `_distribution` | Share of status-mix alerts; fabrication recall unchanged | Status-mix share of alerts falls; no recall loss on other variants |
| W5.5 | **Paradata components** at FSU level: interview-duration distribution vs stratum (`Total_Time_Taken`, `sur_time`), households per survey date, response/substitution code mix | new `pattern/paradata.py` | Catalogue variants "short durations", "one-day completion" | Recall ≥ 0.8 for full-FSU variants at clean alert rate ≤ 2% |
| W5.6 | Near-duplicate households/persons within an FSU (Hamming similarity over ≥ 15 non-identifying responses; pair significance vs the stratum's pair-similarity distribution) | replace `ml/similarity.py` | Duplicate-person and copied-household injections | Copied-household recall ≥ 0.7 at ≤ 1 false pair per 100 FSUs |
| W5.7 | Small-FSU exactness: Monte Carlo exact G for n < 20; drop own-median centring bias by a split-sample estimate | `g_test_p_value`, `_concentration` | Null simulation | p-value uniformity (KS p > 0.01) under null |
| Wording | Group statements remain "this FSU's pattern differs …"; the case page shows group context as context only; the sentence "this does not mean any answer is wrong" is mandatory | `fusion/labels.py`, `explain.py` | UI contract tests | Test asserts the sentence on every group block |

---

## 14. ML remediation

| Model | Decision | Reason (measured) | Change | Gate to stay in the priority path |
|---|---|---|---|---|
| Isolation Forest | **Remove from priority**; keep as optional research output in Technical details | 1.5% / 4.0% alone; drives the ML top-1% | `fusion` ignores it; `ml/engine.py` flag `research_only` | Must exceed chance × 5 at R@1% *and* improve E6 when added (paired CI > 0). Not expected. |
| LOF | **Remove from priority** | Redundant with statistical (hours); lowers B when max-combined | As above | Same |
| Conditional model | **Keep, promote, rebuild** | Positive increment by max (+2.3 / +3.6 pp) | Train on reference rounds and score new data (W3.5); quantile loss for 5–95% intervals (HistGradientBoosting quantile); extend to self-employment earnings, casual daily wages, day-7 hours; State and sector kept; cross-fitting retained for in-round fallback | E7: removing it lowers E6 R@1% (paired CI > 0) |
| Similarity | **Replace** (W5.6) | 0–8% duplicate recall | Near-duplicate group signal | E5 copied-household criteria |
| Categorical consistency model (new, W6) | **Research gate** | The probabilistic component the brief names; covers non-workers (M5) | Chow-Liu tree / small Bayesian network (pgmpy) over status, usual status, industry section, occupation division, education, age band, sex, sector, trained on history with Dirichlet priors; score = conditional tail probability | Must beat contextual on coding/cross-item errors by ≥ 5 pp R@5% (CI > 0); otherwise documented as a negative result and not shipped |

**Rule:** no model stays in the supervisor's priority path because of the project title. "Machine learning" in the delivered product means the conditional expected-value models and, if it earns its place, the consistency model. Both are trained on history and applied to new data, which is exactly Feature 2.

---

## 15. Historical-validation remediation

**Which comparisons are scientifically defensible:**

| Comparison | Defensible? | Condition |
|---|---|---|
| Record value vs the same cell in preceding periods, same design | **Yes** | Applicability-gated; first visit vs first visit; no person linkage |
| Same quarter previous year (pre-2025) | **Yes, where available** | Q3/Q4 2024 vs Q3/Q4 2023 from the de-duplicated axis |
| Same month previous year (post-2025) | **Yes, once 2026 data are supplied** | **REQUIRES HSD** (2026 releases/eSigma) |
| Across the January-2025 redesign at record level | **No** | Different schedule and design |
| Across the redesign at aggregate level | Only for concepts HSD declares comparable, flagged "not like-for-like" | **REQUIRES HSD** concept-comparability table |
| Person-level change over visits | **Yes, within a panel only** (documented 2023-24 key; future panels if supplied) | Revisit files |
| Earnings in real terms | Yes, with an approved CPI series (CPI-IW for wages, or CPI combined) | **REQUIRES HSD approval** of the deflator; CPI is public MoSPI data |

**Work items:**
* **W3.1 Reference snapshots:** `historical/reference.py` builds per design period × period × variable × cell quantiles, plus the conditional-model artefacts, from approved rounds. It is hashed and registered, and scoring reads only snapshots, which also removes the 64-minute 2025 historical stage.
* **W3.2** Same-season reference when available; otherwise rolling window. Both are shown.
* **W3.3** Optional deflation, with the deflator version in provenance.
* **W3.4** Variables:
  * day-7 hours of each activity;
  * 7-day total hours;
  * casual daily wages (CWS 41/51; 22,178 with day-7 wages in 2024);
  * household MPCE (once its formula is transcribed, N11);
  * household size;
  * FSU-level status mix vs the stratum's history.
* **W3.5** Conditional models trained on reference rounds (Feature 2).
* **W3.6 Aggregate:**
  * design-based SEs: Taylor linearisation with FSU as PSU within strata, or a delete-one-FSU jackknife;
  * PSI and Jensen–Shannon for distribution drift by domain;
  * seasonality-aware comparison;
  * an HSD-maintained calendar of known events, so expected changes are labelled rather than alerted.
* **W3.7 Supervisor display:** observation → reference (periods, n) → difference ("about 10× the usual") → what to check.

**Acceptance:**
* E2 recall ≥ the current historical (35.1% / 39.5%) on the confirmation set, with the reference frozen;
* injected domain shifts of +20% detected with power ≥ 0.8 for domains with ≥ 150 adults;
* clean false-notable ≤ 5%;
* no record compared across the design break (test).

---

## 16. Integrity-check framework

**Rule types (W4.1).**
* *Existing:* `allowed_values`, `range`, `required_when`, `value_when`, `not_value_when`, `unique`.
* *New:*

| Type | Example (PLFS) | Integrity class |
|---|---|---|
| `arithmetic` (sum/product with tolerance) | 2025: `tothrs_wrk = Σ hr1..hr7` (**0 violations in 1,148,634**, so a validated hard rule) | Logical |
| `derived_equals` | Day-7 total hours = Σ hours of *work-coded* activities (transcribe from Vol. I; 9,962 / 25,766 differences against the naive sum) | Logical |
| `exists_exactly` (cross-level) | Exactly one head per household (holds for all 101,957 households in 2024) | **Existential** |
| `count_matches` (cross-level) | Household size = number of persons listed | **Existential/referential** |
| `references` (code list) | District code valid for State (district xlsx); NIC-2008 / NCO-2015 codes valid (item-code xlsx) | **Referential** |
| `parent_exists` | Every person row has a household; every household an FSU in the sample list | **Referential** |
| `within_period` | Survey date inside the reference quarter/month | Temporal |
| `soft_range` / `soft_when` (severity warn) | Education level implausible for age; attending school above an age; usual vs current status contradiction | Soft consistency |

**Rule metadata (mandatory):** id, version, type, level (person/household/FSU), severity (hard/soft), concept fields, survey pack and design period (effective from/to), **source citation**, owner, approval status, and ≥ 1 positive and ≥ 1 negative test case.

**Lifecycle (W4.4–W4.5):**
1. Draft in the UI (admin) or as YAML.
2. Automatic test cases.
3. **Dry-run on every stored release.** Hard rules must show ~0 violations on released, post-edit data, or the transcription is wrong.
4. Approval by a second user.
5. Versioned activation.
6. Every finding stores the rule version.

**Acceptance:**
* every brief-named integrity class has ≥ 1 cited rule;
* all rules pass their test cases;
* dry-run reports are stored;
* rule injections are 100% detected through both API and batch.

---

## 17. API / batch ingestion strategy

**Contract (W7.2).** OpenAPI `ingest/v1`:
* `POST /ingest/v1/batches`: manifest plus files (Parquet/CSV in the agreed layout) → batch id;
* `POST /ingest/v1/submissions`: one household with its persons as JSON (schedule id, FSU, household, visit, revision, schema version, payload);
* `GET /ingest/v1/submissions/{id}`: status, rule findings, evidence summary, reference snapshot id.

**Properties:**
* **idempotency key** = (schedule, FSU, household, visit, revision);
* a newer revision supersedes, and history is kept;
* schema validation against the survey pack;
* rule execution at all levels;
* scoring with the **current approved reference snapshot**;
* response p95 ≤ 1 s per household;
* service authentication via OAuth2 client credentials or mTLS (placeholder until the GoI IdP is named).

**Mock eSigma adapter (W7.4).**
* Replays a stored release ordered by `Survey_Date`, in configurable daily batches, through the API.
* **Labelled "mock"** in code, configuration and UI. There is no fake eSigma endpoint.

**Batch (W7.5).** A scheduled job:
1. watch the drop zone;
2. check the manifest and hashes;
3. preprocess;
4. QA gates;
5. score;
6. publish atomically (a new run becomes visible only after all gates pass).

The same scoring core is used as online.

**Equivalence test.** Replaying 2024 through the API with snapshot S gives evidence identical to batch with S (row-level hash).

---

## 18. Related-survey and enumerator strategy

**Related surveys:**
* *Interface (W3.8):* a `related_sources/` adapter that declares:
  * concept, definition, unit, reference period, population and geography level;
  * a comparability rating;
  * a mapping to PLFS concepts.
* *Comparisons are aggregate-only* (State × sector × period), presented as "consistent / differs by X (reasons to consider: definitions …)", never as record evidence.
* *Candidates for HSD to approve:*
  * CPI (deflation; public);
  * HCES (MPCE distribution by State × sector);
  * ASUSE (self-employment earnings);
  * population projections (weight-sum checks).
* **None is fabricated. Each is "NOT POSSIBLE WITH CURRENT DATA" until supplied.**

**Enumerator:**
* Confirmed absent: no investigator code in any supplied layout.
* *Ingestion contract:* optional `investigator_id`, `supervisor_id`, `device_id` and timestamps.
* *Dormant lane (W5.8):* per-investigator duration, completion pace, item non-response, distribution deviation versus peers in the same strata, and heaping. It is activated only when the ID is present, is tested on synthetic IDs, and is labelled "review priority", never misconduct (research doc §13).
* *Until then:* FSU-level paradata alerts are worded as "fieldwork pattern in this FSU". FSU ≠ enumerator.

---

## 19. Security requirements

| Control | Now | Target | Class |
|---|---|---|---|
| Authentication | Optional tokens, **off by default** | **On by default**; OIDC against the GoI-approved identity provider; MFA; session expiry | Pilot-ready (local OIDC) → production **requires MoSPI IdP** |
| Authorisation | 3 roles; decisions role-checked | Roles + **row-level scope** (State/district/FSU assignment); export permission separate | Pilot-ready |
| Audit | SQLite, mutable, actor free text without auth | Postgres append-only, hash chain, INSERT-only role, signed daily digest; read and export logging | Pilot-ready |
| Secrets | Users file | Env/secret store; no secrets in images (already) | Pilot-ready → production **requires MoSPI secret manager** |
| Network | 127.0.0.1 binding | TLS 1.2+ reverse proxy; internal network only; rate limiting | Pilot-ready |
| Encryption at rest | None | Encrypted volumes (LUKS/cloud disk encryption) for Postgres and the object store; encrypted backups | **Requires MoSPI infrastructure** |
| Data exposure | Case pages show microdata to any user | Minimum necessary fields per role; no direct identifiers exist in PLFS, but household keys are treated as confidential | Pilot-ready |
| Exports | Unrestricted CSV | Role-gated, logged, watermarked (user/time), size-limited by role | Pilot-ready |
| Error logs | Default uvicorn | Structured logs without payloads or microdata (scrubbing test) | Pilot-ready |
| Container | Non-root, read-only, cap_drop, no-new-privileges | Plus pinned base digest, SBOM, Trivy scan in CI, signed images | Pilot-ready |
| Dependencies | Pinned versions | Hash-pinned lock, CVE scan gate | Pilot-ready |
| Backups and retention | None | Daily encrypted backups, restore drill; retention per MoSPI policy; log retention per CERT-In directions (180 days is the commonly cited requirement; **to be confirmed by MoSPI's security office**) | **Requires MoSPI policy** |
| Compliance | Not claimed | Control-mapping document against the guidelines MoSPI names (for example CERT-In directions, GIGW, the hosting environment's requirements; DPDP Act applicability to be assessed by MoSPI) | **Requires MoSPI review (G4)** |

**No compliance will be claimed without MoSPI's sign-off.**

---

## 20. eSigma integration boundary

| Concern | Platform owns | eSigma owns |
|---|---|---|
| System of record for survey data and corrections | — | ✔ |
| Validation evidence, queue, decisions, audit | ✔ | — |
| Data in | Ingestion API + contract | Push/export job, field mapping, revision semantics |
| Results out | Decision export / API (case id, decision, reason, corrected value suggestion) | Applying corrections through its own workflow |
| Identity | Accepts tokens from the agreed IdP | IdP |

**Open questions for HSD/eSigma** (each blocks a named item):
1. API style and authentication (blocks W7.2 production).
2. Field mapping and schema versioning (W7.2).
3. Revision/edit semantics (W7.6).
4. Investigator/supervisor IDs and paradata available (W5.8).
5. Pre-scrutiny data access for the pilot (G1).
6. Supervisor review capacity per day (sets the budget, W2.8).
7. Hosting environment (W9).
8. Concept-comparability table across the 2025 redesign (W3.6).
9. Approved related datasets (W3.8).
10. 2026 data for same-month comparisons (W3.2).

---

## 21. Exact implementation roadmap

The order is fixed by dependency:
* **Phase 0** restores a working, honest system.
* **Phase 1** builds the measuring instrument.
* Only then does any method change (**Phases 2–6**).
* Platform work (**Phases 7–10**) can run in parallel with Phases 3–6 once Phase 0 is done.

Each item lists: priority · problem · reason · files · change · expected effect · test · evaluation · dependency · risk · acceptance.

### Phase 0: stop the line (CRITICAL)

**W0.1 Schema compatibility at the read boundary**
* **Priority:** CRITICAL.
* **Problem:** N1. The code reads `MoSPI_*` while every stored run holds `iospi_*`.
* **Reason:** the case page (`fusion/explain.py:274`), `fusion/engine.py:_prepared_identity`, statistical, ML, pattern, contextual, integrity, peer groups and `evaluation/inject.py` all fail on real data.
* **Files:** new `survey_rules/schema.py` with `PREPARED_SCHEMA = {canonical: [aliases]}` and `read_prepared(path, columns)`; call sites in `preprocessing/pipeline.py`, `peer_groups/engine.py`, `statistical/engine.py`, `contextual/engine.py`, `ml/engine.py`, `pattern/engine.py`, `historical/engine.py`, `integrity/engine.py`, `fusion/engine.py`, `fusion/explain.py`, `evaluation/inject.py`; `schema_version` written to new prepared-run metadata.
* **Change:** alias legacy names at read time; never rewrite stored runs. Rejected alternative: re-running preprocessing would change run IDs and break audit provenance.
* **Expected effect:** the current code reads all stored runs.
* **Test:**
  * a unit test with an `iospi_*` fixture and a `MoSPI_*` fixture;
  * new `pytest -m realdata` smoke tests (skipped when data are absent) that call every loader on each stored run and assert non-blank State, sector, period and `ready` share > 95%;
  * the case endpoint on 10 random cases per run returns 200 with person facts.
* **Evaluation:** rerun `pipeline.run --release 2024` into a scratch output root. The sorted (case_id, priority_score) hash must equal the stored `fusion/runs/2024_first_visit_v2`.
* **Dependency:** none.
* **Risk:** a missed call site. Mitigation: grep gate in CI forbidding raw prefixed column literals outside `schema.py`.
* **Acceptance:** all of the above pass; the Docker image rebuilt from the commit passes the 37-check black-box suite **plus** the case-page check.

**W0.2 Fail loudly on missing required columns**
* **Priority:** CRITICAL.
* **Problem:** N2.
* **Reason:** `historical/engine.py: load_release` turns absent columns into `""`.
* **Files:** `historical/engine.py`, and the same pattern in any loader (`grep "set(columns.values()) - set(frame.columns)"`).
* **Change:** required vs optional columns declared; a missing required column raises.
* **Expected effect:** no silent empty evidence.
* **Test:** a fixture missing `state` raises `HistoricalFailure`.
* **Dependency:** W0.1.
* **Acceptance:** the test passes; the real-data smoke test passes.

**W0.3 Run QA gates**
* **Priority:** CRITICAL.
* **Problem:** H10, N2.
* **Files:** `pipeline/run.py`.
* **Change:** after each stage, check:
  * row count equals the prepared count;
  * assessable share within ±10% of the last approved run of the same release/design (configurable);
  * required files present and non-empty;
  * no column entirely null.

  A failed gate stops the pipeline and nothing is published.
* **Test:** fault injection (empty pattern dir; blanked State) → non-zero exit.
* **Acceptance:** both faults are caught.

**W0.4 Reproducible evaluation artefacts**
* **Priority:** HIGH.
* **Problem:** N3.
* **Files:** `evaluation/run.py`.
* **Change:** keep all stage outputs under `evaluation/runs/<protocol>/<seed>/`; the results JSON records the git commit, input hashes, catalogue version and seed. A `--verify` mode recomputes the metrics from artefacts.
* **Acceptance:** `--verify` reproduces every number.

**W0.5 Image provenance and real-data container check**
* **Priority:** HIGH.
* **Files:** `Dockerfile`, `fusion/api.py: /healthz`, `docs/DOCKER.md`.
* **Change:** the image is labelled with the git commit; `/healthz` reports the code version; the black-box suite adds a case-page and an evaluation-page check on real data.
* **Acceptance:** a stale image is detectable; the suite fails on the N1 condition.

**W0.6 Documentation truth check**
* **Priority:** MEDIUM.
* **Change:** a script checks that every file, run and number the docs reference exists or matches its source JSON.
* **Acceptance:** CI passes.

### Phase 1: the measuring instrument (before any method change)

| Item | Pri | Problem | Change (files) | Test | Acceptance |
|---|---|---|---|---|---|
| W1.1 | HIGH | Stylised, narrow injections | `evaluation/catalogue.py`: §12.3 catalogue with parameters; each injection labelled with type, magnitude and level | Unit: each injector changes only labelled fields (hash diff) | 100% of changes labelled |
| W1.2 | HIGH | One seed, six States | `evaluation/run.py`: seeds 1–20, State folds A/B, release loop; resumable | Determinism: same seed → identical labels | — |
| W1.3 | HIGH | N4 metric artefact | `evaluation/metrics.py`: CAPI-pass population; rule list scored separately | Hand-built fixture with known answers | Fixture metrics exact |
| W1.4 | HIGH | No CIs, no paired tests | Paired bootstrap (resample seeds × injected records), Kendall τ, PR curves, subgroup metrics | Known-distribution tests | — |
| W1.5 | HIGH | Post-hoc decisions | `evaluation/PROTOCOL.md`: hypotheses, designs §8.4, selection rule, thresholds §12.5; committed **before** confirmation runs | Review | Commit timestamp precedes confirmation artefacts |
| W1.6 | HIGH | No real-data burden | Burden report on full releases (§12.6) | — | Report generated |
| W1.7 | HIGH | No baseline | Run A0 (current) and the corrected FSU method (W5.1) under the protocol | — | Baseline table published |
| W1.8 | MEDIUM | Plan numbers come from a scratch script | `evaluation/diagnostics.py` reproducing §1/§5 numbers | Numbers equal this plan's | Equal (±0.1 pp) |

**Dependency:** Phase 0. **Risk:** compute time, since 20 seeds × 2 releases × 2 folds = 80 pipeline runs; mitigated by W3.1 snapshots and reuse of unchanged stages.

### Phase 2: evidence and priority redesign

| Item | Pri | Problem | Exact reason | Files | Change | Expected effect | Test | Evaluation | Dep | Risk | Acceptance |
|---|---|---|---|---|---|---|---|---|---|---|---|
| W2.1 | CRITICAL | risk × influence, mean of ranks, override | §5.7 | `fusion/engine.py: fuse`, new `fusion/queue.py`, `fusion/config.py` | Lanes L0–L2 (L3 later); no product with influence; remove override | Stops dilution | Pure-function unit tests per lane | E6 vs A0 | W1.x | UI contract changes | §12.5 E6 criterion |
| W2.2 | CRITICAL | Value evidence split across layers | Per-variable references | `fusion/lanes/value.py` | Per variable: combine statistical (LOO) and historical, then max with conditional; candidates B, C, D | +18–24 pp R@1% indicated | Unit | E1, E2, E4, E6, E7 | W2.9, W3.5 | Overfitting to dev seeds | Selected by the §8.4 rule on confirmation seeds |
| W2.3 | HIGH | Ranks have no stable meaning; forced 1.4% CRITICAL | Within-run ranking | `fusion/calibration.py` | Tail probability against the reference-round score distribution; Šidák/Cauchy across variables | Stable thresholds; controlled false alerts | Calibration tests on held-out clean rounds | §12.5 calibration | W3.1 | Reference-round drift | Observed/nominal 0.8–1.25 |
| W2.4 | HIGH | IF/LOF noise | N6 | `fusion/engine.py: _ml`, `ml/engine.py` | Exclude IF and LOF from lanes; `research_only` flag; still shown in technical details | +1.7 / +3.9 pp (indicated) | — | E4 | W2.1 | — | E7 gate |
| W2.5 | HIGH | Contextual size bias and dilution | M1, §5.4 | `contextual/engine.py`, `fusion/lanes/coding.py` | Dirichlet-smoothed conditional tail probability; separate lane with budget share | Removes 7.7 / 9.9 pp dilution; keeps miscode recall | Size-invariance test (same code rarity, different n → same p within tolerance) | E3 | W2.1 | — | Coding R@5% ≥ current contextual (77% / 62% at 5% on occupation miscodes) |
| W2.6 | HIGH | Override | §5.7 | `fusion/config.py` | Removed (max across lanes and variables replaces it) | — | — | E6 | W2.1 | — | — |
| W2.7 | HIGH | Small-UT distortion | N5 | `fusion/influence.py` → `fusion/impact.py` | Impact = Δ domain estimate ÷ design SE (W3.6); ordering and filter only | Equal treatment of domains | Unit: doubling domain size does not double impact for the same Δ/SE | Burden-by-State | W3.6 | SE instability in tiny domains (floor SE at the national minimum CV) | Max/median State Tier-A rate ≤ 3 on real data |
| W2.8 | HIGH | Bands are ranks | §5.7 | `fusion/queue.py`, `fusion/api.py`, `ui/app.js` | Tiers by calibrated threshold + HSD budget; FSU grouping; per-FSU cap | Queue sized to capacity | API tests | Workload metrics | W2.3 | Budget unknown (default documented until HSD supplies it) | Tier-A size equals budget ±5% |
| W2.9 | MEDIUM | Self-inclusion; quarter pooling | S1, M2 | `statistical/statistics.py`, `peer_groups/config.py` | Leave-one-out placement; pre-2025 quarter boundary with backoff to pooled | Less contamination | LOO unit test | E1 | — | Smaller groups → more backoff | E1 R@1% not lower (paired CI) |
| W2.10 | MEDIUM | Revisit evidence unused | M6 | `fusion/lanes/value.py` | 2023-24 linked change as a value-lane reference for revisit records | Panel coverage | — | E1 on revisit injections | W2.2 | — | Reported |

### Phase 3: historical intelligence first-class

| Item | Pri | Change | Files | Acceptance |
|---|---|---|---|---|
| W3.1 | HIGH | Frozen, hashed reference snapshots + registry; scoring reads snapshots only | `historical/reference.py`, registry table (W7.1) | Snapshot rebuild is deterministic (same hash); the 2025 historical stage ≤ 5 min |
| W3.2 | MEDIUM | Same-season reference when available | `historical/engine.py` | Reported recall difference; no design-break crossing (test) |
| W3.3 | MEDIUM | Optional CPI deflation (approved series) | `historical/deflate.py` | Provenance shows the deflator version; off by default until HSD approves |
| W3.4 | HIGH | Variables: activity hours, 7-day totals, casual daily wages, household MPCE, household size | `survey_rules/plfs.py` (applicability for new items, cited), `historical`, `statistical` | Coverage: ≥ 60% of persons with ≥ 1 value check (from 40%) |
| W3.5 | HIGH | Conditional models trained on reference rounds; quantile intervals; extended targets | `ml/conditional_models.py` | E7 gate; interval coverage 88–92% for nominal 90% on clean held-out data |
| W3.6 | HIGH | Aggregate: design-based SE (FSU PSU, strata), PSI/JS drift, seasonality, known-events calendar | `historical/aggregate.py` | §15 aggregate acceptance |
| W3.7 | MEDIUM | Historical evidence presentation | `fusion/explain.py`, `labels.py` | UI contract tests |
| W3.8 | LOW (gated) | Related-source adapter | `related_sources/` | Spec + test with CPI |

### Phase 4: integrity framework and coverage

| Item | Pri | Change | Acceptance |
|---|---|---|---|
| W4.1 | HIGH | New rule types (§16) in `integrity/engine.py` | Unit tests per type |
| W4.2 | HIGH | Household and FSU levels; cross-level evaluation | Injected cross-level breaches 100% detected |
| W4.3 | HIGH | Code-list referential checks from the supplied xlsx (district, NIC, NCO) | 0 violations on releases, or each explained |
| W4.4 | HIGH | Rule test cases + dry-run report on all releases | Stored reports |
| W4.5 | MEDIUM | Rule registry with approval and versioning; admin UI | Two-person approval enforced (test) |
| W4.6 | HIGH | Transcribe candidate rules with citations (§16 table; N11 items verified against Vol. I before activation) | Each hard rule ~0 on released data |
| W4.7 | MEDIUM | Soft cross-item checks (education/age, usual/current status, attendance/age) as warn-level | Soft-rule burden on real data reported; HSD sets activation |

### Phase 5: FSU / pattern v2

W5.1–W5.8 as in §13 and §18. **Dependency:** W1.x for evaluation. **Priority:** HIGH for W5.1–W5.3 and W5.5; MEDIUM for the rest.

### Phase 6: probabilistic consistency model (research gate)

* **W6.1:** categorical model (§14).
* **W6.2:** evaluation against contextual.
* **Priority:** MEDIUM.
* **Gate:** §14. A negative result is documented and the model is not shipped.

### Phase 7: ingestion, storage, scoring core

| Item | Pri | Change | Acceptance |
|---|---|---|---|
| W7.1 | HIGH | PostgreSQL schema: ingestion registry, cases, decisions/audit, rules, registry, users/scopes, logs; Alembic migrations | Migrations up/down tested |
| W7.2 | HIGH | `ingest/v1` API + OpenAPI | Contract tests; schema rejection tests |
| W7.3 | HIGH | Scoring core refactor: pure functions over (batch, snapshot); used by batch and API | Equivalence test (§17) |
| W7.4 | HIGH | Mock eSigma adapter (replay by survey date) | Clearly labelled mock; replay of 2024 completes |
| W7.5 | MEDIUM | Scheduler + drop zone + atomic publish | Gate-fail blocks publish |
| W7.6 | MEDIUM | Revision handling | Supersession tests |
| W7.7 | HIGH | Audit migration SQLite → Postgres with hash chain | Event counts and hashes reconcile; chain verifier passes; tamper test fails as expected |

### Phase 8: supervisor workflow and outputs

| Item | Pri | Change | Acceptance |
|---|---|---|---|
| W8.1 | HIGH | FSU/household-grouped work lists; assignment by scope | Proxy usability test |
| W8.2 | HIGH | Decision taxonomy + reason codes + corrected-value field | API tests |
| W8.3 | MEDIUM | Time-on-case capture (client and server timestamps) | Reported in dashboard |
| W8.4 | HIGH | Feedback: decisions → per-lane confirmed rates → recalibration report (thresholds proposed, never auto-applied) | Report from synthetic decisions |
| W8.5 | HIGH | Dashboards: workload/progress by area and supervisor; alert rates over time; decision outcomes; drift; model and reference versions | Numbers equal independent SQL |
| W8.6 | MEDIUM | Reports: Excel/PDF; supervisor-wise, geographic, rule, FSU and area | Reconciliation tests |
| W8.7 | MEDIUM | Batch validation from the UI (admin): upload, trigger, monitor, publish | E2E test |

### Phase 9: security to pilot-ready

W9.1–W9.12, one per row of §19:
* auth on by default;
* OIDC;
* scopes;
* TLS proxy;
* export control;
* hash-chained audit (shared with W7.7);
* log scrubbing;
* backups and restore drill;
* image scanning/SBOM/signing;
* lockfile + CVE gate;
* rate limiting;
* the control-mapping document.

**Priority:** HIGH before any pilot. **Acceptance:** each control has an automated test or recorded drill.

### Phase 10: generalisation

* **W10.1:** survey pack `surveys/plfs/`: contracts, concepts, applicability, weights, rules, peer/reference cells and labels, as YAML. Engines read concepts only.
* **Acceptance:** onboard a second schedule (2023-24 revisit as a distinct schedule, or a small synthetic survey) by adding a pack plus at most one adapter module, with all tests passing.

### Phase 11: training and pilot (gated)

* **W11.1:** training pack:
  * supervisor guide;
  * 20 worked cases built from injected errors, with an answer key;
  * an administrator guide;
  * a statistician's methods note.
* **W11.2:** pilot protocol (§12.7) agreed with HSD.
* **Acceptance:** material complete now; delivery and pilot need G1/G6.

**Indicative effort** (one developer-statistician, full time): Phase 0 ≈ 1 week; Phase 1 ≈ 2 weeks; Phase 2 ≈ 3 weeks; Phase 3 ≈ 3 weeks; Phase 4 ≈ 2 weeks; Phase 5 ≈ 2 weeks; Phase 6 ≈ 2 weeks; Phase 7 ≈ 4 weeks; Phase 8 ≈ 3 weeks; Phase 9 ≈ 2 weeks; Phase 10 ≈ 2 weeks; Phase 11 ≈ 1 week of material. **About 27 weeks** in total; Phases 3–6 and 7–9 can overlap with two people.

---

## 22. Tests and evaluations per phase

| Phase | Automated tests | Scientific evaluation | Evidence artefact |
|---|---|---|---|
| 0 | Legacy/current schema fixtures; `-m realdata` smoke; fault injection for QA gates; container case-page check | Byte-equivalent rerun of the 2024 fusion | `docs/evidence/phase0.md` with commands and hashes |
| 1 | Injector-labelling tests; metric fixtures; determinism | Baseline A0 + corrected FSU method, 20 seeds | `evaluation/results/protocol_v1/baseline.json` |
| 2 | Lane unit tests; calibration tests; queue/API contract | E1–E7 on dev seeds → freeze → confirmation seeds; burden on real data | `.../confirmation.json`, decision record |
| 3 | Snapshot determinism; design-break guard; interval coverage | E2, E4 (conditional), aggregate power and false-notable | `.../historical.json` |
| 4 | Rule-type tests; per-rule cases; dry-run | Rule-injection recall; soft-rule burden | Dry-run reports |
| 5 | Null-uniformity simulations; FDR simulations | E5 per fabrication variant; clean-FSU rate by State | `.../fsu.json` |
| 6 | Model unit tests | Gate vs contextual | Gate decision record |
| 7 | API contract, idempotency, revision, equivalence, migration, hash chain | Latency/throughput benchmark | Benchmark report |
| 8 | UI contract; dashboard reconciliation; report reconciliation | Proxy usability study (≥ 5 users, 5 tasks) | Usability report |
| 9 | Auth/scope/export/log-scrub tests; image scan | Restore drill | Control matrix with evidence |
| 10 | Second-pack test suite | — | Onboarding report |
| 11 | — | Pilot (gated) | Pilot report |

---

## 23. Risks and dependencies

| Risk / dependency | Effect | Mitigation |
|---|---|---|
| Design selection overfits the dev seeds | Confirmation underperforms | Pre-registration; separate seeds and State folds; simplest-adequate rule |
| Synthetic errors misrepresent real ones | Good lab numbers, weak field value | Varied catalogue and magnitudes; pilot with an audit sample (G1) |
| Calibration reference contains errors | Thresholds too lenient | Use approved, post-scrutiny rounds as references (the released files are exactly that) |
| HSD budget unknown | Wrong queue length | Documented default; one setting to change |
| Rule transcription errors | False hard findings | Dry-run: hard rules must be ~0 on released data; citations; second-person approval |
| Compute for 80+ evaluation runs | Delay | Snapshots, stage reuse, State subsets per fold |
| eSigma access never granted | No online integration | Mock adapter + API spec delivered; integration marked as an external dependency |
| Security sign-off timeline | No pilot | Pilot-ready controls first; MoSPI review scheduled early |
| Scope creep (Kafka, Spark, deep learning) | Delay without value | Adoption triggers documented (§9) |
| Removing IF/LOF seen as "less ML" | Perception | Evidence table §14; the ML retained is trained on history (Feature 2) and measurably useful |

**External gates (cannot be closed by the team):**
* **G1:** pre-scrutiny eSigma data and supervisor decisions (pilot).
* **G2:** approved related-survey data.
* **G3:** investigator/supervisor IDs and paradata.
* **G4:** MoSPI hosting, identity provider and security review.
* **G5:** eSigma interface agreement.
* **G6:** HSD supervisors for usability testing and training.
* **G7:** 2026 data (same-month history) and an HSD concept-comparability table across the 2025 redesign.

---

## 24. Definition of 10/10

A criterion counts only if **what must exist** exists, **what must be tested** passed, and the **evidence** is reproducible from committed artefacts.

| # | Criterion | Must exist | Must be tested | Evidence that proves it | Achievable now? |
|---|---|---|---|---|---|
| 1 | Problem alignment | §2.3 definition drives the queue; lanes map to brief items | Requirement matrix re-audited against code | Matrix with every row COMPLETE, or gated with a named gate | Yes |
| 2 | Incremental value over deterministic checks | CAPI-pass evaluation | E0 vs E6 on confirmation seeds | E6 R@1% significantly above E0 and above the best single lane (+3 pp, CI > 0) in both releases | Yes (lab); real value needs **G1** |
| 3 | Statistical correctness | LOO, seasonality, calibrated tails, design SEs | Null-calibration and uniformity tests | Observed/nominal 0.8–1.25 on clean held-out rounds | Yes |
| 4 | Survey-design correctness | Applicability, weights, design break, release overlap, panel rules in the survey pack | Guard tests | Tests + real-data checks (published-magnitude reconciliation) | Yes |
| 5 | Historical intelligence | Frozen references, same-season, trained-on-history models, aggregate drift | E2, aggregate power | §15 acceptance met | Yes (same-month 2025 needs **G7**) |
| 6 | Contextual/probabilistic validation | Calibrated coding lane; W6 gate executed | E3 | Coding-lane criteria; W6 decision record (pass or documented fail) | Yes |
| 7 | ML contribution | Only models that pass ablation | E4/E7 | Each retained model lowers recall when removed (CI > 0) | Yes |
| 8 | Group/aggregate detection | FSU v2 + paradata; area drift with design SEs | E5 | Clean alert rate ≤ 2% (FSU), ≤ 5% (area); per-variant recall reported | Yes |
| 9 | Explainability | Lane-aware stories from stored values; group ≠ individual | Contract tests | 100% of displayed numbers traceable to stored fields (test) | Yes |
| 10 | Supervisor usability | §11 workflow | Proxy study, then HSD | Proxy ≥ 90% task completion now; HSD study needs **G6** | Partly |
| 11 | Evaluation quality | Protocol, catalogue, seeds, folds, CIs, burden, reproducibility | `--verify` | Every published number regenerated by one command | Yes |
| 12 | Data architecture | Postgres + Parquet/object store; registry; migrations | Migration and equivalence tests | Reconciliation reports | Yes |
| 13 | Security | §19 controls | Control tests, drills | Pilot-ready matrix now; production needs **G4** | Partly |
| 14 | Scalability | Snapshots, scoring core, benchmarks | Benchmarks | Full 2025 batch ≤ 30 min; API p95 ≤ 1 s/household | Yes |
| 15 | Auditability | Hash-chained audit, read/export logs, versions on every score | Tamper test | Chain verifier report | Yes |
| 16 | eSigma readiness | API spec, mock adapter, boundary doc, open questions | Equivalence and contract tests | Delivered; real integration needs **G5** | Partly |
| 17 | Generalisation | Survey packs | Second-pack onboarding | Config-only onboarding report | Yes |

**Honest ceiling:**
* If every "Yes" row is met and the "Partly" rows reach their internal parts, a strict evaluator should score the platform **about 8.5/10**. The remaining points belong to G1 (real effectiveness), G2/G3 (related surveys, enumerator), G4 (GoI security) and G5/G6 (eSigma, HSD usability).
* **A literal 10/10 requires the HSD/eSigma pilot.** This plan makes the platform ready for that pilot, with the instrument (§12.7) that will show whether it works.

---

## 25. Traceability: 5.5 → 10.0

| Current weakness | Evidence | Root cause | Fix | Validation | Expected outcome |
|---|---|---|---|---|---|
| Committed code cannot read stored runs (N1) | BinderException; FusionFailure; container 22 vs repo 0 `iospi_` files | No schema contract (RC6) | W0.1 | Real-data smoke; byte-equivalent rerun; container case-page check | Working product from the commit |
| Silent empty historical evidence (N2) | 415,549 records blank, `ready = False` | Silent defaulting (RC6) | W0.2, W0.3 | Fault injection | Loud failure; nothing published |
| Fusion worse than parts (C1) | Fair R@1% 21.7% / 17.8% vs 35.1% / 39.5% (historical) | Mean of ranks, max-of-ML, override (RC2) | W2.1–W2.6 | E6/E7, 20 seeds, paired CI | E6 ≥ best single + 3 pp; indicated 39.7–42.0% |
| Headline inflated by rules (C1) | 600 of 1,071 slots | Metric (RC1) | W1.3 | Fixture tests | Headline = CAPI-pass incremental value |
| ML adds nothing / harms (H5) | IF 1.5% / 4.0%; LOF redundant; conditional +2.3 / +3.6 pp when maxed | ML kept for its label (RC3) | W2.4, W3.5, §14 | E4/E7 gates | Only useful, history-trained ML remains |
| Contextual dilution and size bias (M1) | −7.7 / −9.9 pp; ref size 1,353 vs 324 | Uncalibrated surprisal averaged in (RC2) | W2.5 | E3; size-invariance test | Coding lane keeps miscode recall without diluting value checks |
| Influence double-counting, small-UT distortion (H6, N5) | r = 0.59; CRITICAL 20.4% vs 1.15% | Domain-share importance (RC4) | W2.7, W3.6 | Burden by State | Max/median State rate ≤ 3 |
| Bands are ranks, queue too long | 5,700 / 13,238 CRITICAL by construction | Within-run ranking | W2.3, W2.8 | Calibration; budget tests | Queue sized to HSD capacity at a known false-alert rate |
| 60% of persons never prioritised (M5) | 166,722 of 415,549 prioritised | 3 targets; influence gate (RC7) | W2.1, W3.4, W4.7, W6 | Coverage report | ≥ 90% with ≥ 1 non-rule check |
| Integrity facility narrow (H3) | 11 person rules, 6 types | Engine scope | W4.1–W4.7 | Rule tests, dry-runs | Referential/existential/arithmetic/cross-level rules, UI with approval |
| FSU layer unevaluated, dominated by status mix (H4) | 95% status-mix; 27 alerts in 2025; national φ; min-q multiplicity | Method + evaluation (RC1) | W5.1–W5.7 | E5, null simulations | Clean alert ≤ 2%; per-variant recall known |
| Duplicates undetected (M7) | 0–8% recall | Exact hashing | W5.6 | E5 copied-household | ≥ 0.7 recall at ≤ 1 false pair per 100 FSUs |
| No real-time ingestion (H1) | Store-nothing endpoint | Fit-and-score-same-round (RC5) | W3.1, W7.2–W7.6 | Equivalence, idempotency, latency | API ingestion ≡ batch |
| ML not trained on history (F2) | Fitted within round | RC5 | W3.5, W7.3 | E4; registry | Feature 2 satisfied with traceable models |
| Aggregate screening liberal, unevaluated (M4) | SRS SE | Method | W3.6 | Aggregate power / false-notable | ≤ 5% false-notable; stated power |
| Historical narrow (B1) | 3 variables, nominal | Scope | W3.2–W3.4, W3.7 | E2 | Broader, seasonal, optionally deflated comparisons |
| Related surveys, enumerator (H2) | No data / ID | Data (D) | §18 adapters, dormant lane | Synthetic tests | Ready; gated on G2/G3 |
| Single seed, no CIs, artefacts lost (M7, N3) | Stored JSON not re-derivable | RC1, RC8 | W0.4, W1.x | `--verify` | Reproducible, pre-registered evaluation |
| Real effectiveness unknown (C2) | Post-edit data; 0 decisions | Data | W11.2 pilot protocol | Audit-sample design | Measured precision and miss rate (G1) |
| Security prototype (H7, N10) | Auth off; export open; mutable audit | Not built | W9.x, W7.7 | Control tests, drills | Pilot-ready; production after G4 |
| Not survey-general (H8) | PLFS maps in Python | Architecture | W10.1 | Second pack | Config-only onboarding |
| No learning loop (H9) | 0 decisions; no feed | Architecture | W8.4 | Recalibration report | Decisions improve thresholds under human approval |
| Batch not from UI; reports CSV only (M10, M11) | — | Scope | W8.6, W8.7 | E2E, reconciliation | Feature 5 and 7 complete |
| Training absent (O4) | — | Scope | W11.1 | Material review | Pack ready; delivery on G6 |
| Unused paradata and household data (N7) | Durations, dates, time disposition, MPCE unused | Scope (RC7) | W3.4, W5.5, W4.6 | E5 paradata variants; coverage | New, evidence-backed signals at FSU and record level |

---

### Appendix: decisions this plan asks you to approve

1. Phase 0 before anything else, including the schema read-boundary approach in W0.1, which never rewrites stored runs.
2. The evaluation protocol (§12) and the selection rule (§8.4) are fixed **before** method changes.
3. Isolation Forest and LOF leave the priority path; contextual becomes a separate coding lane; influence stops multiplying risk.
4. PostgreSQL is introduced for operational state only; analytical data stays in Parquet.
5. Kafka, Spark, Airflow and Kubernetes are deferred, with documented adoption triggers.
6. The honest ceiling (§24) is communicated to HSD, with the gates G1–G7 requested formally.
