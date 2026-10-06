# PLFS V1 ML validation design

## Purpose and boundary

This layer produces four separate forms of anomaly evidence from one prepared PLFS person delivery. It is not an editing, classification, prioritisation, fraud-detection, or error-probability system. It never changes source values and never says that an observation is wrong.

The implementation consumes only the immutable `prepared_persons.parquet` contract and the matching issued `peer_groups` run. It verifies preprocessing-run, release, observation and design-period provenance before doing work. No release is pooled with another; model fits are additionally separated by release, observation type, design period, visit and (for 2025) month.

## Actual contracts used

Prepared records supply `MoSPI_record_key`, `MoSPI_source_row`, `MoSPI_release`, `MoSPI_observation`, `MoSPI_design_period`, `MoSPI_visit`, optional `MoSPI_month`, `MoSPI_state`, `MoSPI_sector`, `MoSPI_fsu`, `MoSPI_weight`, and `MoSPI_prepared_status`. The record-facing source ID is the existing peer-layer convention: `MoSPI_record_key + "|person=" + source person serial`.

The peer run supplies `peer_group_assignments.parquet` and `peer_group_references.parquet`. LOF uses only the issued `day7_total_hours` assignment, never constructs a new group. The peer run already carries release, observation, design period, visit, month, `peer_group_id`, size, grouping definition, backoff level, reference preprocessing run, and specification version.

The ML source mappings are release-specific in `config.py`. They use only age, sex, education, CWS status, supplied occupation/industry, day-7 hours, and the two documented current-week earnings fields. `MoSPI_weight` is excluded. Raw record keys, source rows, FSU, household/person serials and all other identifiers are excluded from feature and signature values.

## Components

### Isolation Forest

V1 uses scikit-learn Isolation Forest with 25 trees, one CPU worker, and fixed seed `20260925`. A deterministic SHA-256 selection limits fit data to 10,000 rows and each tree to 1,024 sampled rows. It scores every assessable ready row in its release/observation/design/visit/month boundary. This conservative CPU budget is a V1 evidence configuration, not a claim that all anomalies are captured.

Features are five-year age band (to avoid treating documented age-heaping as a raw anomaly), log1p non-negative day-7 hours and earnings (V1.1: a value whose item does not apply to the person is missing, with an indicator, not a 0), plus one-hot encoded sex, education, CWS status, one-digit occupation group and two-digit industry division. Numeric missing values are median-imputed with indicators; categorical missingness is explicit. A row needs valid age and CWS status; otherwise it is `NOT_ASSESSABLE`. `raw_model_score` is `-score_samples`, where larger means more isolated. `evidence_rank` is its within-boundary empirical rank, not a probability.

If a documented field is wholly absent in an observation route (notably day-7 hours in revisit), it is removed from that route's model rather than made into an imputed constant; `effective_feature_columns` records this.

### Peer-scoped LOF (V1.1)

Within each existing first-visit day-7-hours peer group, LOF uses numeric age, day-7 hours and log1p salaried/self-employed earnings, robust-scaled. V1.0 fitted on all rows; PLFS answers are discrete, so many rows were identical, their k-distance was 0, local reachability densities became infinite and 14,087 records scored above 10^6 (audit H7). V1.1 fits each group on its **distinct** feature vectors (every fitted point then has a positive k-distance and the factor is a finite density ratio, about 1 for ordinary points), keeps k fixed at 20, and marks a group `INSUFFICIENT_DISTINCT_PEER_VALUES` when it has no more than 20 distinct vectors (with k close to the number of distinct points every neighbourhood is "everyone" and LOF cannot discriminate). Identical answers are never in themselves treated as unusual. `evidence_rank` is the percentile of the factor among all assessable records of the run (V1.0 ranked within each group, so every group contributed its own "top 5%").

### Gradient-boosted conditional model (V1.1)

Target: first-visit salaried earnings for the preceding calendar month, **only for persons to whom the item applies** (CWS 31/71/72) and with a positive amount. V1.0 trained on all persons, 89% of whom carry a placeholder 0; with 30 boosting rounds the model could not move from the near-zero baseline to earners' log-earnings, so its estimate was a median 47% of the comparison-group median for 97.6% of earners (audit C1). V1.1:

* population: applicable positive earners; applicable zeros are `APPLICABLE_ZERO_EARNINGS_NOT_MODELLED`, non-applicable rows `TARGET_NOT_APPLICABLE_FOR_CWS_STATUS`;
* predictors: age, day-7 hours, sex, education, CWS status, occupation major group, industry division, **State/UT and sector** (native categorical splits); the target is never a predictor;
* two-fold cross-fitting with folds formed by **FSU** (no household member is predicted by a model that saw its household);
* `HistGradientBoostingRegressor` on log(earnings), learning rate 0.1, at most 500 rounds with deterministic early stopping (10% internal validation, 20 rounds patience; about 195 rounds on 2024), training capped at 50,000 stable records per fold;
* evidence: `|log(observed) − predicted log|`; outputs `predicted_value = exp(prediction)` (a central model estimate, not the median of any group), `observed_to_estimate_ratio` and `log_residual`.

Real-data check (2024, 46,760 earners): median observed ÷ estimate 1.014 (IQR 0.77–1.33); State medians 0.98–1.08; estimate ÷ peer median 0.994 with 50.7% below (V1.0: 0.474 and 97.6%); top-1% flags are two-sided (32% above, 68% below the estimate).

### Similarity

The safe V1 implementation is blocked exact response-pattern matching only. A signature hashes at least six populated non-identifying response values from age, sex, education, CWS status, occupation, industry, day-7 hours, and both earnings values. Values are compared only inside a block of release, observation, design period, visit, month, state, sector and FSU. FSU is a blocking constraint—not a compared signature value and never an interviewer identifier.

This avoids unsafe national all-pairs matching. Non-exact/high-similarity matching is **NOT IMPLEMENTED**: the available public data and V1 compute budget do not justify a distance metric or a threshold. An exact match emits only the bounded wording: “Repeated/highly similar response pattern requiring verification.” It never declares a duplicate.

## Assessability and provenance

Every component emits `ASSESSABLE` or `NOT_ASSESSABLE`, with a machine-readable reason. Records with absent support are never silently treated as normal. Outputs retain source observation/record IDs, release, observation type, design period, visit, month, method and feature versions, preprocessing run ID, raw evidence value, rank where meaningful, statement, and applicable peer/reference metadata. Scores are intentionally never averaged or fused.

## Limitations

- The prepared delivery has no reviewed field-level applicability masks. V1 treats required missing values conservatively as not assessable rather than inferring applicability.
- The conditional model is one numerical target only; it does not supply categorical probabilities or a modelled “correct” value.
- LOF is limited to existing first-visit day-7-hours peer assignments; it does not create peer groups for revisit.
- Exact similarity is intentionally narrower than near-duplicate detection. Its matches require verification.
- No model has confirmed error labels, calibration, error-rate estimates, influence weighting, fusion, threshold-based actions, or correction workflow.
