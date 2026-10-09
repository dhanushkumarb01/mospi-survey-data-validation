# PLFS Pattern / Group / Temporal Evidence — V1 design

## Current method: `plfs-pattern-v2.0` (October 2026)

* **FSU-level alerts** (W5.2): each FSU's dispersion-adjusted check p-values are combined with the Cauchy combination test (valid under dependence) and Benjamini–Hochberg is applied across FSUs (`fsu_summary.parquet`). The old "minimum q over ~10 checks" did not control the FSU-level false discovery rate.
* **Local dispersion** (W5.3): φ per State × sector where ≥ 30 FSUs are assessed, national otherwise (`dispersion_scope`).
* **Age/sex-standardised status mix** (W5.4): expected status counts from leave-FSU-out age-band × sex rates; an FSU is not flagged for its demography.
* **Fieldwork paradata** (W5.5, `fieldwork.py`): interview duration (one-sided), share of households interviewed on one day (empirical p among comparable FSUs), response-code mix, substitution share. Worded as fieldwork patterns, never as an enumerator (no investigator code exists).
* **Near-duplicate persons across households** (W5.6): pairs agreeing on ≥ 95% of ≥ 15 jointly answered items, tested against the comparable-FSU pair rate.
* Not done: Monte Carlo exact G for very small FSUs (W5.7). None of this has been evaluated (clean-FSU alert rate, per-variant recall).

## Purpose and scope

Pattern V1.1 produces aggregate evidence for human review: whether an FSU or time series has an unusual response pattern relative to a carefully bounded reference. It does not decide that a record is wrong, infer an error probability, correct data, attribute a pattern to an enumerator, or combine scores with Statistical, Contextual, or ML evidence.

The module is separate because Statistical evidence is individual peer-conditioned placement, Contextual evidence is conditional response frequency, and ML evidence is model/similarity based. Pattern is FSU/group/time-level evidence.

## Input, boundaries, and reference population

The engine accepts exactly one prepared-person delivery with adjacent preprocessing metadata. It verifies release, observation route and design period in both metadata and Parquet values. Raw release field mappings are taken from the existing preparation/peer-group contracts.

The dedicated Pattern reference is leave-FSU-out membership of the same `release`, `observation_type`, `design_period`, `visit`, `month`, `state`, `sector`, and `stratum`. FSU is a group identifier, never an enumerator identifier. This is intentionally not the existing peer-group machinery: peer groups are target-specific person-level behavioural contexts and exclude FSU, whereas this component needs a group distribution and reference excluding that FSU.

No release, observation route, pre/post-2025 period, or post-2025 month is pooled. January 2025 is therefore a hard structural boundary. Temporal calculations operate only within one prepared release; cross-break comparisons are absent rather than normalized into a drift score.

## Components and working methods (V1.1)

V1.0 ranked raw distances (Jensen–Shannon, median/IQR, IQR rank). The audit found that these ignored FSU size (small FSUs ranked systematically more unusual: Spearman −0.47 for age heaping), that the IQR rank counted ties 1.5 times (22,795 positions above 1, negative scores), that earnings checks mostly measured the share of non-earners (placeholder zeros), and that 48–70% of earnings/hours heaping statements claimed a direction the numbers did not support. V1.1 replaces every score with a test whose p-value accounts for the FSU's size; the evidence score is −log10(p), ranks order these scores, and Benjamini–Hochberg q-values (within component and variable) decide what is "notable" (q < 0.05).

**Clustering (overdispersion) correction.** The tests treat people as independent, but answers are clustered within FSUs (neighbours resemble each other), so genuine between-FSU variation is larger than the tests expect. The first controlled evaluation measured the consequence: 15.8% (2024) and 54% (2025, smaller monthly cells) of *clean* FSUs were "notable". Each component/variable therefore applies a quasi-likelihood correction: p-values are converted to 1-df chi-square equivalents (one-sided tests: signed normal deviates), the dispersion factor φ is their median over all FSUs divided by the null median 0.455 (floored at 1), statistics are divided by φ, and p-values, scores, ranks and BH q-values are recomputed. `p_value_unadjusted` and `dispersion_factor` are stored. This assumes most FSUs are ordinary (standard practice); a release where most FSUs genuinely differed would be under-flagged.

1. `fsu_distribution_shift`
   * categorical (activity status, occupation group, industry division): G-test of the FSU's counts against leave-FSU-out proportions (+0.5 per-category continuity; Williams' correction; chi-square approximation — approximate for FSUs of 10–15 people). Jensen–Shannon distance and the largest-difference category are kept as effect sizes.
   * numeric (age; earnings and day-7 hours **only among persons for whom the item applies**): two-sided Mann–Whitney U. The statement names a direction only from the medians, and says "the medians are equal" when they are.
2. `reduced_variance_concentration`: location-free one-sided binomial test — the share of FSU values within ±(reference IQR/2) of the FSU's own median, against the reference share within the same window of the reference median. "Values vary less than usual" is written only when the FSU share is larger. (Centring on the FSU's own median makes small-FSU p-values slightly optimistic; documented.)
3. `digit_heaping`: **age only** — one-sided binomial test of the share of ages ending in 0 or 5 against the comparable share (the established age-heaping signal). Rupee earnings are routinely reported in round amounts and day-7 hours (0–24) are not a terminal-digit measure, so those digit tests were removed. "Higher" is stated only when the FSU share exceeds the reference share.
4. `temporal_drift`: unchanged formula; in first-visit files every FSU is observed in a single quarter/month, so rows are `FSU_OBSERVED_IN_ONE_PERIOD_ONLY` (the audit's "0 of 63,745 assessable" was a design incompatibility, not a bug). Aggregate temporal drift is provided by the separate `historical/` layer.
5. `revisit_transition_patterns`: the FSU's rate of linked revisit changes in the tails of their comparison groups, tested against the comparable rate with a two-sided binomial test.

## Minimum support and non-assessability

Defaults are working configuration, not optimum statistical thresholds: FSU 10, reference 30, valid target 10, temporal group 10, two preceding periods, and linked revisit population 10. Missing/invalid targets, small FSUs/references, no history, zero reference spread, unavailable revisit data and incompatible provenance are never converted to normal evidence. They retain explicit machine-readable reason codes.

## Outputs and provenance

Each run writes component Parquet files and `pattern_evidence.parquet`, with component identity, FSU/group identifiers, boundaries, target, population/reference counts, raw metric, evidence score/rank, status/reason, deterministic statement, method/spec version, preprocessing run ID and Pattern run ID. `details_json` contains component-specific quantities without inventing meaningless columns. A report and metadata capture parameters, inputs and output paths.

Record-level anomaly scores and record-to-pattern attachments are not emitted: group membership is not evidence that an individual record is anomalous. A future Fusion specification can define an explicit semantic attachment table.

## Reproducibility, limitations, and future work

Rows and output fields are deterministically sorted; evidence IDs hash component/group/target/period identity. Tests establish software behavior, not real-world error detection accuracy. There is no ground-truth error dataset, weighting, estimator influence, seasonality model, enumerator ID, post-2025 revisit delivery, or confirmed HSD transition taxonomy. Future work includes HSD-verified transition definitions, seasonally comparable histories, design-weighted aggregate checks, and a separately evaluated fusion stage.
