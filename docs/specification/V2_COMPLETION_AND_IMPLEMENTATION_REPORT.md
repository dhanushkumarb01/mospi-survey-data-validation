# V2 completion and implementation report — MoSPI Intelligent Survey Data Validation Platform (PLFS)

**Date:** 9 October 2026. **Scope:** the existing V2 working tree (no parallel system). **Companion documents:** [`10_10_IMPROVEMENT_PLAN.md`](10_10_IMPROVEMENT_PLAN.md) (plan and status), [`../evaluation/PROTOCOL.md`](../evaluation/PROTOCOL.md) (pre-registered evaluation protocol).

Every number in this report comes from a stored run, a log or a test listed in §H. Where evidence does not exist the report says so.

Words used for status: **Implemented** (code exists and runs), **Tested** (automated tests check its behaviour), **Evaluated** (its error-finding value has been measured on injected or real errors), **Partial**, **Deferred** (deliberately left to a later stage or gated on HSD/eSigma input).

---

## A. Executive summary

**What V2 does now.** For a prepared PLFS delivery (2023-24, Calendar 2024, 2025 monthly), one batch run builds comparison groups, then checks each person's earnings, wages and hours against comparable people in the same round, the same cell in earlier periods, and an expected-value model trained only on earlier periods; checks occupation coding; checks 20 approved questionnaire rules at person and household level (22 defined, 2 inactive drafts); and tests every FSU for unusual patterns. The result is a workload-bounded review list ("Check now" / "Check if time") with plain-language reasons, FSU group alerts kept separate from record cases, a supervisor workspace with decisions, a hash-chained audit trail, CSV export and — new in this sprint — a working "Batch validation" page that starts and monitors real batch runs.

**Completed in this sprint** (details in §C):
1. Calibration defects found and corrected with stated statistical reasons: discrete-test (Tarone) multiplicity in the value lane; State-conditional (Mondrian) conformal calibration of the expected-value models; the FSU combination's p = 1 veto removed and three measurably mis-calibrated fieldwork checks moved from "alert" to "context". New runs `v2_2` for 2024 and 2025 (stored V2.1 runs untouched).
2. Batch validation from the workspace (W8.7): real pipeline execution in a separate process, job status, errors, interrupted-job detection, admin-only start, link from a finished job to its dashboard, worklist, cases/export and FSU alerts.
3. First runs of the pre-registered evaluation for the current method (development seeds; reduced scope disclosed in §D).
4. The 2023-24 release re-run with the current method for the first time (`v2_2`, all stages, 23 minutes), started through the new batch API. All quality gates passed; the earlier `v2` run is untouched.

**Separate conclusions.**

| Question | Answer |
|---|---|
| Operationally usable for a supervised pilot on stored releases? | **Yes, with limits**: batch start → review list → case evidence → decision → audit → export works end to end on stored, prepared releases; no browser upload, no eSigma connection, CSV only. |
| Scientifically evaluated? | **Partially.** One development seed per release (fold A, seed 1) of the pre-registered protocol was run and verified: the current value lane finds 47.7% (2024) and 56.5% (2025) of CAPI-passing injected errors in the top 1% of records, against 34.2% and 42.1% for the superseded V2.0 priority (paired difference +13.4 and +14.4 points, 95% CIs above 0). But the expected-value model **alone** does better than the full lane (by 2.9 and 6.4 points), so "combined beats parts" is **not** met. The pre-registered confirmation set (15 seeds × 2 releases on fold B) has **not** been run. |
| Ready for an HSD pilot? | **Not yet as a decision tool; ready as a supervised trial** once HSD supplies review capacity (budget), named users/roles and a pilot data path (gates G1, G4, G6). Real-world precision is unknown until supervisors record decisions on pre-scrutiny data. |

**Targets still missed** (§D, §E):
* observed/nominal value alerts 2025 = **0.73** (target 0.80–1.25; 2024 now 0.82, met);
* highest/median State "Check now" rate 2024 = **3.51**, 2025 = **3.06** and 2023-24 = **3.44** (target ≤ 3), driven by a drift in Nagaland's reported hours (2024), Lakshadweep's tiny calibration set (2025) and small UTs (2023-24: A&N, Puducherry);
* combined value lane does **not** beat the best single lane (the expected-value model) — acceptance criterion 1;
* FSU level: the clean-FSU alert rate now meets ≤ 2% (0.97% / 0.11% of assessable FSUs on real data; 0.97% / 0.11% of clean FSUs in the evaluation copies) only because three uncalibrated fieldwork checks were made context-only; injected short-interview, one-day and copied-household FSUs are then almost never found (0–7%).

---

## B. Full implementation inventory

| Area | What exists | Status | Evidence |
|---|---|---|---|
| Data ingestion and schema compatibility | Release contracts (`preprocessing/config.py`); prepared persons/households; schema read boundary for legacy `iospi_*` and current `MoSPI_*` columns (`survey_rules/schema.py`); stored runs never rewritten | Implemented, tested | `survey_rules` and reader tests; real-data smoke tests read every stored legacy fusion run (§H) |
| Online ingestion (API that stores submissions) | `POST /api/validate/record` screens one record, stores nothing | Partial (prototype); ingestion store deferred (PostgreSQL/eSigma later stage) | endpoint test |
| Preprocessing and survey design | Applicability gating (CWS rules), documented final weights, release-overlap de-duplication, January-2025 design boundary, first-visit/revisit separation | Implemented, tested | `survey_rules` tests |
| Peer groups | State × sector × status × occupation/industry with back-off (min 30); quarter boundary pre-2025, month in 2025 (spec v1.1) | Implemented, tested | `peer_groups/tests` |
| Statistical (current round) | Leave-one-out finite-sample tail probabilities for 4 variables | Implemented, tested; **evaluated only in this sprint's development runs** | §D |
| Contextual / coding | Conformal frequency tail probability of the occupation code; own small budget share | Implemented, tested; evaluated in development runs (§D) | |
| ML models and training-window discipline | Gradient-boosted expected-value models for 4 targets, trained on strictly earlier periods (2024: 16 of 16 fits; 2025: 44 of 52, January uses a labelled in-round cross-fit); split-conformal tail probabilities, **State-conditional since this sprint**; model registry per run. Isolation Forest/LOF research-only | Implemented, tested | `ml/tests`; `ml/runs/*_v2_2/model_registry.json` |
| Pattern / FSU / fieldwork / duplicates | Leave-FSU-out tests (distribution shift with age-sex standardisation, heaping, concentration), local dispersion factor, paradata checks (short interviews, one-day completion, response codes, substitution), near-duplicate persons; FSU combination + BH across FSUs | Implemented, tested; **combination corrected in this sprint**; three fieldwork checks context-only (§E); FSU detection value not established | `pattern/tests`; §D group-level results |
| Historical comparison and reference snapshots | Same cell in earlier periods (out-of-sample), same-season comparison pre-2025, design-based SEs for area screening, hashed reference snapshot per run | Implemented, tested; record-level evaluated in development runs (§D); area screening not evaluated | `historical/tests` |
| Integrity rules | 16 person + 6 household rules (20 approved, 2 inactive soft-rule drafts; YAML, cited, self-tested on load, dry run per batch); approval metadata only | Implemented, tested; rule recall 100% on injected rule breaches (§D) | `integrity/tests`; §D |
| Fusion, prioritisation, budgets | Lanes (rules / value / coding), Šidák combination with Tarone count (v2.2), budget 1% (provisional), FSU cap, Tier B, impact (Δ domain mean ÷ design SE) for ordering only | Implemented, tested; evaluated in development runs | `fusion/tests`; §D |
| Explanations and evidence | Plain-language case story per lane; evidence cards | Implemented, tested (UI contract); not tested with users | `fusion/tests/test_explain.py`, `test_ui_contract.py` |
| Dashboard, worklist, case view, decisions | Overview, worklist by FSU/household, all cases with filters, case page, decision form with reason codes, verification source, corrected value, time on case | Implemented, tested | `fusion/tests`, `pipeline/tests/test_pipeline.py` |
| Audit trail and feedback | Append-only SQLite, hash chain, verifier, legacy rows sealed; feedback report proposing (never applying) changes | Implemented, tested; 0 real decisions so far | `fusion/tests/test_review.py` |
| API and batch workflow | Read API; **batch start/status/list (new)**; admin-only start when sign-in is on | Implemented, tested (§F, §H) | `pipeline/tests/test_jobs.py` |
| Exports and reporting | CSV export of any list (role-gated, logged); fusion/pattern/ML run reports | Partial: no Excel/PDF, no supervisor-wise reports | |
| Tests, quality gates, run artefacts | 153 tests (140 default + 13 real-data opt-in); QA gate after every stage; reproducible evaluation artefacts with `--verify` | Implemented, tested | §H |
| Documentation and deployment | README, design notes per layer, Docker files with provenance; eSigma roadmap | Partial: Docker image **not rebuilt or tested** in this sprint; no GoI security review | |

---

## C. Changes made in this sprint

### C1. Discrete-test (Tarone) multiplicity in the value lane — fusion v2.2
* **Files:** `fusion/lanes.py`, `fusion/engine.py`, `fusion/queue.py` (`budgets`, `value_threshold`), `fusion/config.py` (`discrete_test_correction`, version `MoSPI-fusion-v2.2-lanes`); tests in `fusion/tests/test_fusion.py`.
* **Reason (measured on the stored V2.1 runs).** A finite-sample two-sided tail probability against *n* comparable values cannot be below 2/(*n*+1). Current-peer groups have median size 77 (5th percentile 32), so their floor (~0.026) is above the value threshold (0.022). In 2024 only 56% of reference rows could reach the threshold at all. Yet the Šidák correction counted every mechanism and variable, which halved the expected-value model's power: at the threshold, current-peer p fired at 0.07× nominal, earlier-period p at 0.28×, the model at 1.06×, and the combined record p at 0.51×.
* **Before:** every available mechanism and variable is counted in Šidák. **After:** a mechanism (or variable) whose smallest attainable p is above the run's value threshold is not counted (Tarone 1990). The count is made against the threshold itself, not threshold/k, so it is never smaller than Tarone's and the correction remains valid. The model is always counted. A guard checks that the threshold used here equals the queue's. Every fusion report now has `burden.calibration_by_mechanism`.
* **Evidence:** 2 new unit tests; the read-only simulation predicted 0.82 (2024) and 0.73 (2025), and the re-runs measured 0.823 and 0.733 (§E).
* **Regression risk:** more cases reach "Check now" (2024: 1,927 → 3,079; 2025: 5,444 → 7,634), still within budget (4,156 / 11,487). One end-to-end test assumed the injected ×10 salary is the first row of the value list; within a tier the list is ordered by impact, so the test now looks the case up (the "strongest evidence" assertion is unchanged and passes).

### C2. State-conditional (Mondrian) conformal calibration of the expected-value models — ML v2.1
* **Files:** `ml/conditional_models.py`, `ml/config.py` (`conformal_group_minimum = 100`, version `plfs-ml-v2.1`); test `ml/tests/test_conditional_models.py`.
* **Reason.** Split-conformal p-values are calibrated only on average over the calibration set. Model p at the threshold was 2.05× nominal in Delhi, 2.41× in A&N Islands and 1.60× in Gujarat, but 0.83× in Uttar Pradesh (2024 V2.1). That concentrated "Check now" in some States and UTs.
* **Before:** one national set of calibration residuals per model. **After:** residuals are kept per State when the State has ≥ 100 calibration residuals (floor 1/101 < 0.01), and the national set is used otherwise. The model registry records `states_calibrated_separately` and the number of scored records calibrated by State.
* **Evidence:** a new unit test (heteroscedastic States: pooled calibration over-flags the wide State, per-State calibration restores both). Real data: §E.
* **Regression risk / side effect:** States with a genuine change between quarters are now judged against their own earlier quarters, so a real drift shows up more clearly. Nagaland 2024 moved from 0.66× to 2.18× (its rate rises from 0.98× in Q3 to 4.01× in Q6, mostly low day-7 hours). Small UTs below the minimum (Lakshadweep) still use national calibration.

### C3. FSU combination: p = 1 veto removed; three uncalibrated fieldwork checks made context-only — FSU combination v2
* **Files:** `pattern/engine.py` (`fsu_summary`, `CONTEXT_ONLY_COMPONENTS`, `FSU_COMBINATION_METHOD`), `fusion/engine.py` (recombines a stored pattern run's checks when its summary predates the current method, so the pattern stage is not re-run); tests in `pattern/tests/test_fieldwork.py`.
* **Reason 1 (an implementation defect).** The Cauchy combination maps p = 1 to tan(−π/2) ≈ −1.6 × 10¹⁶, which forces the FSU's combined p to 1 whatever its other checks show. 86% of 2024 FSUs (44% in 2025) had such a check, mostly "no near-identical pair". So the 2024 rate of 0.43% looked compliant only because evidence was being silently vetoed.
* **Reason 2 (measured mis-calibration).** At p ≤ 0.01 on released data, short interviews fired at 13.4× / 15.9× nominal, near-duplicate persons at 2.1× / 4.9×, and response-code mix at 5.1× / 2.8×. Every other check was ≤ 1.8×. These tests treat households, or person pairs, in an FSU as independent, and the median-based dispersion factor does not correct the tail. With the veto removed and all checks counted, 8.0% (2024) and 5.6% (2025) of FSUs alert.
* **Before:** Cauchy combination of all checks. **After:** min(1, k × smallest p) over the counted checks (valid under any dependence), then BH across FSUs. The three checks are kept with the FSU for display (`context_only_notable_checks`) but are not counted. The criterion: ≤ 3× nominal at p ≤ 0.01 in both releases.
* **Evidence:** 2 new unit tests; real data §E; evaluation §D.
* **Regression risk (material and accepted for now):** the FSU lane no longer finds injected short-interview, one-day or copied-household FSUs (0–7%). Counting them would find 93% of short-interview FSUs (2024) but alert on 7.5% of clean FSUs. §I lists the recalibration needed. FSU alerts still never move a record or create record cases (`fusion/queue.py` does not read them; FSU context is only attached for display).

### C4. Batch validation from the workspace — W8.7
* **Files:** `pipeline/jobs.py` (new), `fusion/api.py` (4 endpoints, admin-only start), `fusion/ui/app.js` and `index.html` ("Batch validation" page and job page), `pipeline/tests/test_jobs.py` (6 tests).
* **Before:** batches ran only from the command line. **After:** see §F.
* **Regression risk:** the UI start-up no longer stops when no run exists (it opens the batch page instead). The API module now imports `pipeline.jobs`, which is lightweight and has no heavy dependencies at import time.

### C5. Selective stage re-run — `pipeline/run.py`
* `--reuse-suffix <old> --rerun <stages>` re-runs only the named stages under a new suffix and reuses the earlier suffix's directories, which are read and never modified. This is how `v2_2` was produced without re-running peer, statistical, contextual, pattern, historical and integrity.

### C6. Evaluation results visible in the workspace
* `/api/evaluation` now also returns a summary of every `evaluation/results/protocol_v1/*.json` labelled *development* or *confirmation*, and the Technical reference page shows it, replacing the sentence "has not been run yet".

---

## D. Scientific evaluation

**Scope: preliminary (development) evaluation. The full protocol was NOT completed.** Of the protocol's 40 runs (seeds 1–5 on fold A for development and seeds 6–20 on fold B for confirmation, in each release), **2 development runs** were made: seed 1, fold A, for 2024 and for 2025. That is enough to compare designs and find defects, but not to accept or reject the method under the pre-registered criteria. Each run re-executes the whole pipeline on an injected copy (12 and 34 minutes), so the 30 confirmation runs need about 12 hours of single-machine time.

**Method (unchanged protocol, `evaluation/PROTOCOL.md`).** A copy of the prepared release, restricted to fold A States/UTs (18 of 36, assigned by size A, B, B, A, ...), receives 300 errors of each record type from catalogue `plfs-injection-catalogue-v2`: ×10, ÷10, ×12, ×100, digit transposition, plausible-but-wrong earnings from another State, casual wage ×10, occupation miscode, hours keying, duplicate person, and two rule-breaking types. 2025 injects in February–December only. It also receives 30 FSUs each of fabrication, copied households, short interviews (durations ÷ 3) and one-day completion. For 2024 the 2023-24 copy of the same States serves as clean history. The full V2.2 pipeline is run on the copy. Headline metrics use the **CAPI-pass population** (records breaking a hard rule and the rule-type injections removed). Baseline **A0** is the superseded V2.0 priority, rebuilt from the same stage outputs.

**Exact configuration.** Code `c72fd8f35b12+uncommitted-changes` (this sprint's working tree, fusion v2.2, ML v2.1, FSU combination v2). Injection seeds 20261004 (plan seed + 1). Commands:
```
python -m evaluation.run --release 2024 --seeds 1 --fold A     # 689.7 s
python -m evaluation.run --release 2025 --seeds 1 --fold A     # 2016.2 s
python -m evaluation.run --verify evaluation/results/protocol_v1/2024_A_seed1.json   # VERIFIED
python -m evaluation.run --verify evaluation/results/protocol_v1/2025_A_seed1.json   # VERIFIED
```
Results: `evaluation/results/protocol_v1/{2024,2025}_A_seed1.json` (with input SHA-256, catalogue, commit, timings). Artefacts: `evaluation/runs/protocol_v1/<release>_A_seed1/`. Logs: `evaluation/logs/`.

| | 2024 | 2025 |
|---|---:|---:|
| Records in the copy / CAPI-pass | 211,213 / 210,478 | 623,191 / 622,045 |
| CAPI-pass injected record errors | 2,833 | 2,497 |
| K at 1% (= review budget) | 2,105 (budget 2,113) | 6,220 (budget 6,232) |

**Recall (R) and precision (P) at K, CAPI-pass population** (precision is a lower bound: unlabelled records may hold real errors).

| Design | 2024 R@0.5% | R@1% | P@1% | R@5% | AP | 2025 R@0.5% | R@1% | P@1% | R@5% | AP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A0 superseded V2.0 | 22.9 | 34.2 | 46.1 | 64.5 | .376 | 33.1 | 42.1 | 16.9 | 65.4 | .280 |
| E1 current peers | 18.2 | 30.6 | 41.2 | 70.1 | .313 | 23.9 | 37.0 | 14.8 | 68.5 | .121 |
| E2 earlier periods | 25.6 | 41.7 | 56.1 | 72.7 | .454 | 34.2 | 48.2 | 19.3 | 72.2 | .207 |
| E4 expected-value model | **28.2** | **50.6** | **68.1** | **78.4** | **.558** | **45.0** | **62.9** | **25.3** | 77.3 | .313 |
| B references (E1+E2) | 23.4 | 40.0 | 53.8 | 73.5 | .420 | 30.0 | 48.2 | 19.4 | 72.0 | .170 |
| **D full value lane** | 27.2 | 47.7 | 64.1 | 77.8 | .530 | 41.3 | 56.5 | 22.7 | 77.1 | .284 |
| **E6 operational queue** | 26.7 | 49.1 | 66.1 | 81.7 | .536 | 38.9 | 56.7 | 22.7 | **79.5** | **.334** |

**Paired bootstrap differences of R@1%** (500 resamples of injected records; the first four are pre-specified in `evaluation/run.py`, the last three are **post-hoc**, computed read-only from the same artefacts):

| Difference | 2024 | 2025 |
|---|---|---|
| D − A0 | **+13.4** [+11.3, +15.6] | **+14.4** [+12.5, +16.4] |
| E6 − A0 | **+14.9** [+12.7, +16.9] | **+14.5** [+12.6, +16.4] |
| D − E2 | +6.0 [+3.9, +8.1] | +8.4 [+6.2, +10.4] |
| D − B | +7.7 [+5.8, +9.6] | +8.3 [+6.3, +10.2] |
| D − E4 (post-hoc) | **−2.9** [−4.2, −1.7] | **−6.4** [−7.4, −5.2] |
| E6 − E4 (post-hoc) | −1.4 [−2.8, −0.0] | −6.2 [−7.7, −4.9] |
| E4 − A0 (post-hoc) | +16.3 [+14.3, +18.3] | +20.8 [+18.9, +22.7] |

**Recall at 1% by error type, D (A0):** 2024 — ×100 84% (91%), ×12 65% (53%), ×10 60% (55%), ÷10 60% (15%), hours keying 90% (39%), casual wage ×10 52% (40%), digit transposition 24% (12%), plausible-but-wrong 18% (18%), duplicate person 1% (1%). 2025 — ×100 99% (94%), ×12 85% (69%), ×10 74% (64%), ÷10 77% (18%), casual wage ×10 80% (58%), digit transposition 39% (20%), plausible-but-wrong 18% (26%), duplicate person 0% (0%). (In 2025 all 300 hours-keying injections break rule R13, weekly hours total, so the rule list catches them and they are outside the CAPI-pass population. Likewise 108 (2024) and 171 (2025) duplicate-person injections break a rule.)

**Other criteria.**
* Rules: 600 of 600 rule-type injections found in each release (recall 100%) — criterion 7 met.
* Coding lane: occupation miscodes found in the top 5% — 82.3% (2024) and 69.3% (2025), against 77% / 62% for the superseded contextual layer — criterion 4 met on this seed.
* FSU level (criterion 6), share of injected FSUs alerted, with the current combination: fabrication 100% / 50%; copied household 3% / 0%; short interviews 0% / 0%; one-day completion 7% / 0%; clean-FSU alert rate 0.97% / 0.11%. **Post-hoc**, counting all checks as before this sprint: short interviews 93% / 17%, copied household 10% / 3%, one-day 13% / 3%, but clean-FSU alert rate 7.5% / 5.5%.
* Runtime (pipeline stages on the copy, seconds): 2024 — peer 39, statistical 51, contextual 15, ML 94, pattern 255, historical 103, integrity 17, fusion 33; 2025 — 103, 132, 36, 359, 613, 354, 67, 123.

**What can be concluded.**
1. On these two development runs, the current method finds **substantially more** CAPI-passing injected errors within a 1% budget than the superseded V2.0 priority, in both releases, with paired CIs well above zero. The largest gains are on lost zeros (÷10) and hours keying.
2. Combining evidence does **not** yet beat the best single lane. The expected-value model alone is significantly better than the full value lane in both releases (−2.9 and −6.4 points). A post-hoc "model first, references only where no model" variant recovers part of the gap (+0.1 / +2.2 points over D) but is still below the model alone (−2.8 / −4.2). One plausible cause is the Šidák factor across variables, which E4 does not apply. This is a development finding to resolve before the confirmation runs (§I), not a result.
3. Criteria 4 (coding) and 7 (rules) hold on this seed. Criterion 5 (burden) is partly met (§E). Criterion 6 (FSU) is not established: the false-alert rate is low only because the checks that could find paradata and copying problems are not counted.
4. Plausible-but-wrong values (a real value from another State) and duplicate persons stay largely undetected by every design (≤ 26% and ≤ 1% at 1%).

**What cannot be concluded.** Nothing here is a confirmation result. Fold B and seeds 6–20 have not been run, and the protocol's selection rule has not been applied. Injected errors are stylised. Real-world precision and miss rate need supervisor decisions on pre-scrutiny eSigma data (gate G1).

---

## E. Calibration results

**Sources.** `fusion/runs/<release>_first_visit_<suffix>/fusion_report.json`, keys `burden.observed_over_nominal`, `burden.check_now_state_rate_max_over_median` (States/UTs with ≥ 1,000 records; computed in `FusionEngine._report`), and `group_alerts` (HIGH + MEDIUM over FSUs with an FSU q-value; `FusionEngine._groups`, `pattern.engine.fsu_summary`). V2.1 = stored runs `v2_1` (unchanged); V2.2 = this sprint's runs `v2_2` (only ML and fusion re-run; the other stages are the V2.1 runs).

| Metric | 2024 V2.1 | 2024 V2.2 | 2025 V2.1 | 2025 V2.2 | Target | Met? |
|---|---:|---:|---:|---:|---|---|
| Observed / nominal value alerts | 0.514 | **0.823** | 0.521 | **0.733** | 0.80–1.25 | 2024 yes; 2025 **no** |
| Highest / median State "Check now" rate | 3.27 | **3.51** | 4.73 | **3.06** | ≤ 3 | **no** (both) |
| FSUs with a group alert | 55 / 12,748 = 0.43% | 124 / 12,748 = **0.97%** | 394 / 13,392 = 2.94% | 15 / 13,314 = **0.11%** | ≤ 2% | yes (see caveat) |
| "Check now" cases (budget) | 1,927 (4,156) | 3,079 (4,156) | 5,444 (11,487) | 7,634 (11,487) | — | — |

**Observed/nominal by mechanism at the run's threshold (V2.2 reports, `burden.calibration_by_mechanism`).** 2024: current peers 0.16, earlier periods 0.42, model 1.07, combined variable 0.82. 2025: 0.25, 0.42, 0.97, 0.73. The model is calibrated. The references stay conservative because of ties (26% of current-peer values sit at p = 1, from rounded amounts) and discreteness that Tarone's count cannot remove when the reference *can* reach the threshold but rarely does.

**Model calibration by State (observed/nominal at the threshold, V2.1 → V2.2).** 2024: Delhi 2.05 → 1.23, A&N 2.41 → 1.70, Gujarat 1.60 → 1.02, Maharashtra 1.43 → 0.70, Uttar Pradesh 0.83 → 0.99, **Nagaland 0.66 → 2.18**, Lakshadweep 2.14 → 2.14. 2025: DNH & DD 1.89 → 1.59, A&N 1.41 → 1.01, Lakshadweep 2.76 → 2.76.

**Explanation of each remaining deviation.**
* *2025 observed/nominal 0.73.* Not a threshold problem: the model mechanism is at 0.97. The deficit comes from the conservative references, combined by Šidák with the model. Making the references "exact" would need randomised or mid-p tie-breaking (not adopted: randomness in an official decision, or loss of validity) or a different combination (see §D finding 2). **Next evidence:** the development seeds 2–5 comparing combinations, then confirmation.
* *2024 State ratio 3.51.* Nagaland: 25.4 "Check now" per 1,000 against a median of 7.2. Its model rate climbs by quarter (Q3 0.98×, Q4 1.51×, Q5 2.45×, Q6 4.01×), and 89 of its 114 "Check now" cases are day-7 hours, 86 of them *lower* than expected. This is a concentration of values unusual compared with Nagaland's own earlier quarters, which is the temporal-drift signal the brief asks for. It was hidden under national calibration. It should be checked with HSD as an area-level question (fieldwork, season or genuine change) rather than tuned away. Without Nagaland the next highest State is A&N at 2.6× the median.
* *2025 State ratio 3.06.* Lakshadweep: 22.1 per 1,000 (26 cases among 1,176 persons). It has no usable current-peer or earlier-period reference in 2025 and too few calibration residuals for State calibration, so it falls back to national calibration (2.76×). **Next evidence:** a pooled small-UT calibration group, or HSD's view on whether Lakshadweep should be reviewed with island/UT peers.
* *FSU alerts.* The target is now met, but by excluding three checks whose p-values are invalid, not by making them valid. The 2024 V2.1 figure (0.43%) was itself an artefact of the p = 1 veto. Counting all checks correctly would give 8.0% / 5.6%.

**Separation preserved.** Impact orders cases within a tier and never changes a tier (`fusion/queue.py`, test `test_impact_orders_within_a_tier_but_never_changes_the_tier`). FSU alerts are attached to cases for display only. The queue never reads `fsu_notable` or `fsu_q_value`, and no record is promoted because its FSU alerted.

---

## F. UI and operational workflow

**User journey (works today).**
1. *Batch validation* page (left menu) lists the prepared deliveries present on the server: survey round, data file, number of persons, what it is compared with, run labels already used, availability.
2. An administrator (any user when sign-in is off; the name is then stored as unverified) chooses the round and a new run label and presses **Start batch validation**. *Advanced* lets technical staff reuse an earlier run and recompute only chosen steps (used in this sprint for `v2_2`).
3. The job page shows status (Starting, Running, Completed, Failed, Stopped by a quality check, Interrupted), the current step, per-step time and quality check, and the last log lines; it refreshes every 5 s.
4. On completion: **Open dashboard / Open worklist / All cases and CSV export / FSU group alerts** switch the workspace to the new run. Case pages show the reason, the comparisons (current peers, earlier periods, model estimate), what to check, and the FSU context; decisions go to the run's audit trail.

**Backend actions.** `GET /api/batch/inputs`, `POST /api/batch`, `GET /api/batch`, `GET /api/batch/{job_id}` (`fusion/api.py`), implemented by `pipeline/jobs.py`, which spawns `python -m pipeline.jobs run <job>` → `pipeline.run.run_pipeline` (all stages, quality gates). Job records and logs: `pipeline/jobs/`; run report: `pipeline/runs/<release>_<label>.json`.

**Safeguards.** Supported inputs only (prepared deliveries of a documented release contract); stored runs immutable (a used label is refused with 409); one job at a time; failures and quality-gate stops reported with the error text, nothing published; a vanished process is reported as *Interrupted*; start is admin-only when sign-in is enabled; review decisions, audit history and existing runs are not touched.

**Supported inputs.** The three prepared releases in `pipeline/run.py` `PRESETS`: 2023-24 (first visit with revisit), Calendar 2024 (history: 2023-24), 2025 (monthly). **Upload is not implemented**: a new delivery must be prepared on the server with `python -m preprocessing ...` (which checks the release layout) and added as a preset. The page says this explicitly; there is no upload button.

**Known limitations.** No upload; no scheduler/drop zone; no cancel button (a running job is stopped by ending its process, then shows *Interrupted*); progress is per step, not a percentage; a full 2025 batch needs about 47 minutes and several GB of memory; jobs are local to one server (no queue service).

---

## G. Release status

| Release | Runs kept (unchanged) | Current-method run | Status |
|---|---|---|---|
| **2023-24** (first visit + revisit) | `v1` stage runs; `fusion/runs/2023_24_first_visit_v2` (superseded V2.0 priority) | **`v2_2`** (new; every stage fresh: peer 80 s, statistical with revisit 160 s, contextual 38 s, ML 249 s, pattern with revisit 633 s, historical 131 s, integrity 35 s, fusion 70 s) | 418,159 persons; 3,110 "Check now" (budget 4,182: 3,100 value, 10 coding); 0 hard-rule findings; observed/nominal **0.825**; State ratio **3.44** (A&N, Puducherry, Chandigarh — small UTs; not met); FSU alerts 127 of 12,743 (1.0%). Models: 12 fits trained on earlier quarters, 8 in-round cross-fits for the first quarter (no earlier period). No earlier release is used as history (by design). Not evaluated by injection (the protocol uses 2024 and 2025). |
| **2024** (Calendar 2024, history 2023-24) | `v1`, `v1_clean`, `v2` (V2.0), **`v2_1`** (V2.1, 8 Oct pass) | **`v2_2`** (ML + fusion re-run; other stages from `v2_1`) | §E. One development evaluation run (§D). |
| **2025** (monthly design) | `v2` (V2.0), **`v2_1`** | **`v2_2`** (ML + fusion re-run) | §E. One development evaluation run (§D). |
| Evaluation copies | `evaluation/runs/2024_injection`, `2025_injection` (superseded catalogue v1) | `evaluation/runs/protocol_v1/{2024,2025}_A_seed1/` | Development only; separate from release runs and never shown as review lists (they are not under `fusion/runs`). |

The workspace lists current-method runs first (latest round first: 2025 `v2_2`); every stored run, including V2.0 runs, can still be opened (15 real-data smoke tests, §H). Review decisions are stored per run, so decisions recorded on a `v2_1` run stay with that run.

---

## H. Verification summary

All commands were run from the repository root on 9 October 2026 (Windows 11, Python 3.11.9, 12 cores, 16.8 GB RAM).

| Command | Purpose | Outcome |
|---|---|---|
| read-only diagnostics on `fusion/runs/*_v2_1/value_evidence.parquet`, `pattern/runs/*_v2_1/*.parquet` (scratch scripts, not committed) | Trace the three metrics; simulate Tarone, combination and calibration effects before changing code | Simulation 0.82 / 0.73 confirmed exactly by the re-runs |
| `pytest fusion/tests/test_fusion.py ml/tests/test_conditional_models.py` | New Tarone and Mondrian tests | 19 passed |
| `pytest pipeline/tests` (after C1) | End-to-end synthetic batch | **1 failed** (`test_supervisor_api_on_a_lane_run`: a "first row" assumption, see C1); fixed; 5 passed |
| `pytest pattern fusion/tests/test_fusion.py` | FSU combination tests | 33 passed |
| `python -m pipeline.run --release 2024 --suffix v2_2 --reuse-suffix v2_1 --rerun ml,fusion` | 2024 V2.2 | COMPLETED, all QA gates passed; ML 185.8 s, fusion 67.4 s. Its fusion step had loaded the FSU code before C3, so that fusion directory (created minutes earlier by this sprint) was removed and fusion alone re-run (67.7 s). The value-lane figures of the two fusion runs were identical (0.823, 3.51, 3,079 "Check now"); only the FSU alerts changed (55 → 124). `pipeline/runs/2024_v2_2.json` therefore shows ML as "reused" |
| `python -m pipeline.run --release 2025 --suffix v2_2 --reuse-suffix v2_1 --rerun ml,fusion` | 2025 V2.2 | COMPLETED, all QA gates passed; ML 649.5 s, fusion 197.4 s |
| `pytest pipeline/tests/test_jobs.py` | Batch workflow: inputs, refusals, real job start → COMPLETED, open result, duplicate/concurrent refusal, reuse + recompute, failure reporting, interrupted detection, admin-only | 6 passed (real subprocess pipeline runs on synthetic data) |
| `python -m fusion.serve --port 8765` + `curl` | Endpoints on the real stored runs: inputs listed (3 releases), duplicate label refused (409), page and script served | as expected |
| synthetic dry run of `evaluation.run.evaluate` (throw-away protocol folder, deleted) | Harness runs end to end before real runs | completed; `--verify` VERIFIED |
| `pytest fusion/tests` | Including UI contract | 38 passed |
| `pytest` (default suite) | Regression | **140 passed, 13 skipped** (real-data opt-in), 0 failed; final run after all edits: **140 passed, 15 skipped** (the real-data tests are parametrised over stored runs) |
| `pytest -m realdata --realdata` | Every stored run (legacy V2.0, V2.1, V2.2) readable; case pages open | **14 passed**; re-run after the 2023-24 `v2_2` run: **15 passed** |
| `python -m evaluation.run --release 2024 --seeds 1 --fold A` and `--release 2025` | Development evaluation | completed (689.7 s, 2016.2 s) |
| `python -m evaluation.run --verify …` (both) | Reproducibility | VERIFIED, VERIFIED |
| read-only post-hoc scripts on the evaluation artefacts | D − E4, FSU trade-off, "model first" variant | reported in §D, labelled post-hoc |
| 2023-24 batch started through `POST /api/batch` on a local server | Real-data test of the batch workflow and the 2023-24 rerun | job `a6fbc51c…` COMPLETED in 1,400 s; all 7 quality gates PASSED; run `2023_24_first_visit_v2_2` listed in `/api/runs` |

**Not run (skipped deliberately):** fold-B confirmation seeds (time); development seeds 2–5; Docker build and container tests (out of scope); browser-automation tests of the new page (the page was checked by syntax check, the UI contract tests and the served-asset check, not clicked through in a browser); full-pipeline reruns of the unchanged 2024/2025 stages.

---

## I. Remaining work and handover

| # | Issue or missing feature | Why it matters | Evidence still required | Recommended next action | Depends on | Blocks pilot? |
|---|---|---|---|---|---|---|
| 1 | Full value lane is below the expected-value model alone (−2.9 / −6.4 points at 1%) | The combination should add value, not remove it (criterion 1) | Development seeds 2–5 on fold A comparing D, E4, "model first" and D without the Šidák-over-variables factor | Run `python -m evaluation.run --release <r> --seeds 2-5 --fold A` once per candidate (stage outputs can be reused; only fusion differs), freeze the simplest design within 2 points of the best, and record the decision in PROTOCOL.md before confirmation | Compute time only | No (but blocks any accuracy claim) |
| 2 | Confirmation runs not done | Without them no acceptance criterion is established | Seeds 6–20, fold B, both releases (~12 h) | `python -m evaluation.run --release 2024 --seeds 6-20 --fold B` (and 2025) after item 1 | Compute time | No for a supervised trial; yes for any claim of accuracy |
| 3 | Short-interview, near-duplicate and response-code checks are context-only | Paradata and copying are the brief's "unusual response patterns"; they currently find 0–7% of injected cases | A version whose p-values hold on released data (≤ 2× nominal at 0.01) | Compare each FSU with *FSUs* (not households) of the same stratum and quarter; adjust durations for household size; then restore to the alert and re-evaluate | Compute; HSD view on paradata | No (FSU alerts are context), but weakens the pilot's FSU value |
| 4 | 2025 value alerts at 0.73 of nominal | Budget is under-used (7,634 of 11,487) | Item 1's combination choice | Re-measure after item 1; do not move thresholds | — | No |
| 5 | State concentration (Nagaland 2024, Lakshadweep 2025) | Over-review of some areas | HSD explanation of Nagaland Q5–Q6 day-7 hours; small-UT calibration choice | Show Nagaland as an area-level drift item; pool small UTs for calibration | HSD input | No |
| 6 | Review capacity (budget 1%) is a placeholder | Sets the length of every list | Cases per supervisor-day and number of supervisors | HSD supplies the figures; set `review_budget_share` | HSD (G6) | **Yes** |
| 7 | Real-world precision and miss rate unknown | The only evidence that matters to HSD | Supervisor decisions on pre-scrutiny data plus a random audit of unflagged records | Pilot protocol (plan §12.7) | eSigma data, HSD (G1) | **Yes** (it is the pilot's purpose) |
| 8 | No browser upload / ingestion store | New deliveries need technical staff | — | Keep server-side preparation for the pilot; ingestion API and PostgreSQL in the eSigma stage | eSigma (G5) | No |
| 9 | Identity, hosting, security review | GoI deployment requirement | MoSPI identity provider, hosting, security audit | Integrate OIDC/TLS in MoSPI's environment | MoSPI (G4) | **Yes** for any deployment beyond a local trial |
| 10 | Docker image not rebuilt or tested with this sprint's code | The container would serve old code | `docker compose build` + smoke test | Rebuild with `MOSPI_CODE_VERSION`; run `/healthz` and the real-data smoke tests in the container | — | Yes for a container-based pilot |
| 11 | Excel/PDF reports, rule-approval UI, training pack | Brief features 6–7, objective 4 | — | After the pilot design is agreed | HSD | No |
| 12 | Evaluation of area-level drift screening, revisit lane | Brief "temporal drift" | Injected domain shifts | Add to the protocol | — | No |
| 13 | Batch jobs: no cancel button, single server | Operational convenience | — | Add cancel (terminate the job's process and mark it) | — | No |

---

## J. Final honest assessment

1. **Functional implementation — substantially complete for batch validation of stored, prepared PLFS releases.** Every stage runs with quality gates, review lists are produced, explanations are shown, decisions are audited, and batches can now be started and followed from the workspace. Not implemented: online ingestion with storage, browser upload, Excel/PDF reports, rule-approval UI, enumerator lane (no identifier in the data).
2. **Scientific evidence — preliminary.** Two development runs show a large, statistically clear gain over the superseded V2.0 priority (+13 to +14 points of recall at a 1% budget). They also show that the current combination is *worse* than its best component, the expected-value model, so the method is not yet in its final form. The confirmation protocol has not been run. No real-world accuracy evidence exists. Calibration improved: 2024 alert rate within target, State disparities reduced except where real drift or tiny UTs drive them. 2025 alert rate (0.73) and both State ratios (3.51 / 3.06) still miss their targets.
3. **Operational completeness — usable for a supervised trial, not for routine operation.** The workflow from batch start to decision works, but the review budget is a placeholder, there is no upload or scheduler, FSU paradata checks are not alerting, and the workspace has not been tested with HSD users.
4. **Security and deployment readiness — not ready.** Local-only by default; optional token roles with admin-only batch start; hash-chained audit. There is no GoI-approved identity, TLS, hosting or security review, and the container image has not been rebuilt with this sprint's code.
5. **HSD pilot readiness — ready to *start planning* a supervised pilot, not to run one unsupervised.** Prerequisites: HSD review capacity (budget), named users and roles, a pre-scrutiny data path from eSigma, a decision on items 1–3 of §I, and a rebuilt, tested deployment. Until supervisors' decisions exist, every statement about real error-finding value remains unproven.

No overall score is assigned. The work does not justify "10/10": no acceptance criterion has been tested on the confirmation set; on the development set criterion 2 (beats the superseded design) holds but criterion 1 (combined beats best single lane) fails; criterion 5 is partly missed; criterion 6 is met only by not counting three checks.
